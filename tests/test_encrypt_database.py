"""The one-time command that encrypts an existing plain database."""

import os
import shutil
from datetime import date
from pathlib import Path

import pytest
import sqlcipher3.dbapi2 as sqlcipher
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app import demo_data, encrypt_database
from app.core.db import apply_key, get_engine
from app.core.startup import (
    ALEMBIC_INI,
    SQLITE_HEADER,
    check_database_is_current,
)
from app.encrypt_database import (
    IN_PROGRESS_SUFFIX,
    EncryptionRefusedError,
    plain_copy_path,
)
from tests.conftest import TEST_DATABASE_KEY, use_database_key

TODAY = date(2026, 11, 15)


def table_counts(path: Path, key: str | None) -> dict[str, int]:
    connection = sqlcipher.connect(str(path))
    try:
        if key is not None:
            apply_key(connection, key)
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            # Names from sqlite_master, not from outside.
            name: connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]  # noqa: S608
            for name in names
        }
    finally:
        connection.close()


@pytest.fixture(scope="module")
def filled_plain_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A plain database, migrated and filled with the demo data (customers,
    forms, plans, check-ins: every kind of row and trigger). Built once for
    the whole file, as filling it is slow; tests work on copies."""
    folder = tmp_path_factory.mktemp("filled")
    with pytest.MonkeyPatch.context() as monkeypatch:
        for name in list(os.environ):
            if name.startswith("GYM_"):
                monkeypatch.delenv(name)
        monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
        monkeypatch.chdir(folder)
        use_database_key(monkeypatch, None)
        command.upgrade(Config(ALEMBIC_INI), "head")
        with Session(get_engine()) as db, db.begin():
            demo_data.fill(db)
        # Closing the last connection folds the WAL into the file, so the
        # file alone is the whole database.
        use_database_key(monkeypatch, None)
    path = folder / "gym.db"
    assert not path.with_name("gym.db-wal").exists()
    return path


@pytest.fixture
def plain_db(filled_plain_db: Path, alembic_config: Config, isolated_env: Path) -> Path:
    """This test's own copy of the filled plain database, with the key set
    (conftest), as before running the command."""
    path = isolated_env / "gym.db"
    shutil.copyfile(filled_plain_db, path)
    return path


def test_encrypts_the_database_and_keeps_the_original(plain_db: Path) -> None:
    before = table_counts(plain_db, None)
    assert before["customers"] > 0

    kept = encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)

    assert kept == plain_db.with_name("gym.db.plain-2026-11-15")
    assert not plain_db.read_bytes().startswith(SQLITE_HEADER)
    assert table_counts(plain_db, TEST_DATABASE_KEY) == before
    # The original, untouched apart from its name.
    assert kept.read_bytes().startswith(SQLITE_HEADER)
    assert table_counts(kept, None) == before
    # Nothing left over beside them.
    assert sorted(p.name for p in plain_db.parent.glob("gym.db*")) == [
        "gym.db",
        "gym.db.plain-2026-11-15",
    ]


def test_the_apps_start_on_the_encrypted_database(plain_db: Path) -> None:
    encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)

    check_database_is_current()
    with get_engine().connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_main_says_where_the_readable_original_is(
    plain_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    encrypt_database.main()

    out = capsys.readouterr().out
    assert "is now encrypted" in out
    assert "WARNING" in out
    assert ".plain-" in out
    assert TEST_DATABASE_KEY not in out


def test_refuses_without_a_key(plain_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_database_key(monkeypatch, None)

    with pytest.raises(SystemExit, match="GYM_DATABASE_KEY isn't set"):
        encrypt_database.main()

    assert plain_db.read_bytes().startswith(SQLITE_HEADER)


def test_refuses_a_missing_database(isolated_env: Path) -> None:
    with pytest.raises(EncryptionRefusedError, match="no database at"):
        encrypt_database.encrypt_database(
            isolated_env / "gym.db", TEST_DATABASE_KEY, TODAY
        )


def test_refuses_a_database_that_is_already_encrypted(plain_db: Path) -> None:
    encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)

    with pytest.raises(EncryptionRefusedError, match="already encrypted"):
        encrypt_database.encrypt_database(
            plain_db, TEST_DATABASE_KEY, date(2026, 11, 16)
        )


@pytest.mark.parametrize("leftover", ["in progress", "plain copy"])
def test_refuses_when_a_file_from_an_earlier_run_is_there(
    plain_db: Path, leftover: str
) -> None:
    path = (
        plain_db.with_name(plain_db.name + IN_PROGRESS_SUFFIX)
        if leftover == "in progress"
        else plain_copy_path(plain_db, TODAY)
    )
    path.write_bytes(b"something")

    with pytest.raises(EncryptionRefusedError, match="already exists"):
        encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)

    assert path.read_bytes() == b"something"
    assert plain_db.read_bytes().startswith(SQLITE_HEADER)


def test_refuses_a_database_in_use(plain_db: Path) -> None:
    # Like an app still running, in the middle of a read.
    app = sqlcipher.connect(str(plain_db), isolation_level=None)
    app.execute("BEGIN")
    app.execute("SELECT count(*) FROM customers").fetchone()
    try:
        with pytest.raises(EncryptionRefusedError, match="in use"):
            encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)
    finally:
        app.execute("ROLLBACK")
        app.close()

    assert plain_db.read_bytes().startswith(SQLITE_HEADER)
    assert not plain_db.with_name(plain_db.name + IN_PROGRESS_SUFFIX).exists()


def test_a_copy_that_fails_its_check_is_removed(
    plain_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad_copy(*_: object) -> None:
        raise EncryptionRefusedError("the copy's customers rows differ")

    monkeypatch.setattr(encrypt_database, "_check_copy", bad_copy)
    before = table_counts(plain_db, None)

    with pytest.raises(EncryptionRefusedError, match="rows differ"):
        encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)

    # Still plain and whole. (Not byte for byte: the export moved it out of
    # WAL mode, which the apps switch back on at their next connect.)
    assert plain_db.read_bytes().startswith(SQLITE_HEADER)
    assert table_counts(plain_db, None) == before
    assert sorted(p.name for p in plain_db.parent.glob("gym.db*")) == ["gym.db"]


def test_a_failed_swap_puts_the_original_back(
    plain_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = Path.rename

    def rename(self: Path, target: Path) -> Path:
        if self.name.endswith(IN_PROGRESS_SUFFIX):
            raise PermissionError("file in use")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    before = table_counts(plain_db, None)

    with pytest.raises(PermissionError):
        encrypt_database.encrypt_database(plain_db, TEST_DATABASE_KEY, TODAY)

    assert plain_db.read_bytes().startswith(SQLITE_HEADER)
    assert table_counts(plain_db, None) == before
    assert sorted(p.name for p in plain_db.parent.glob("gym.db*")) == ["gym.db"]


def test_refuses_an_empty_file(isolated_env: Path) -> None:
    path = isolated_env / "gym.db"
    path.touch()

    with pytest.raises(EncryptionRefusedError, match="is empty"):
        encrypt_database.encrypt_database(path, TEST_DATABASE_KEY, TODAY)


def test_explains_a_run_cut_off_during_the_swap(plain_db: Path) -> None:
    # As after a power cut between the two renames: the original already
    # moved aside, the checked copy not yet in its place.
    encrypted = plain_db.with_name(plain_db.name + IN_PROGRESS_SUFFIX)
    plain_db.rename(plain_copy_path(plain_db, TODAY))
    encrypted.write_bytes(b"the checked copy")

    with pytest.raises(EncryptionRefusedError, match="stopped half-way") as error:
        encrypt_database.encrypt_database(
            plain_db, TEST_DATABASE_KEY, date(2026, 11, 16)
        )

    assert "gym.db.encrypting" in str(error.value)
    assert "gym.db.plain-2026-11-15" in str(error.value)
