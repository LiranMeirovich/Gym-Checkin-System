"""Restoring a backup: the round trip, every refusal leaving things as they
were, and the replaced files kept aside (app/restore_backup.py)."""

import shutil
from pathlib import Path

import pytest
import pyzipper
import sqlcipher3.dbapi2 as sqlcipher
from alembic import command
from alembic.config import Config

from app import restore_backup
from app.core import backups
from app.core.config import get_settings
from app.core.db import apply_key, get_engine
from app.restore_backup import RestoreRefusedError, restore
from tests.conftest import AddMigration, use_database_key

# Made up; real passwords and keys never appear in the repo.
PASSWORD = "not-a-real-backup-password-" + "x" * 8
OTHER_KEY = "cd" * 32


@pytest.fixture
def backup_password(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> bytes:
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    return PASSWORD.encode()


def mark(note: str) -> None:
    """Leave a mark in the live database, to tell versions of it apart."""
    with get_engine().begin() as connection:
        connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS marks (note TEXT)")
        connection.exec_driver_sql(f"INSERT INTO marks VALUES ('{note}')")  # noqa: S608


def marks(path: Path = Path("gym.db")) -> list[str]:
    connection = sqlcipher.connect(str(path))
    try:
        key = get_settings().database_key_hex
        if key is not None:
            apply_key(connection, key)
        has_marks = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'marks'"
        ).fetchone()
        if not has_marks:
            return []
        return [row[0] for row in connection.execute("SELECT note FROM marks")]
    finally:
        connection.close()


def stop_the_apps() -> None:
    """The apps' connections closed, as when both are stopped."""
    get_engine().dispose()


def folder_files(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


@pytest.mark.usefixtures("backup_password")
def test_a_restore_brings_back_the_database_and_reports(
    backup_password: bytes,
) -> None:
    mark("in the backup")
    reports = Path("reports")
    reports.mkdir()
    (reports / "report-2026-10.pdf").write_bytes(b"made-up October")
    backup = backups.make()
    # Life goes on after the backup.
    mark("after the backup")
    (reports / "report-2026-11.pdf").write_bytes(b"made-up November")
    stop_the_apps()

    restored = restore(backup, backup_password)

    assert marks() == ["in the backup"]
    assert folder_files(reports) == {"report-2026-10.pdf": b"made-up October"}
    # The replaced ones are kept aside, never deleted.
    assert restored.kept_database is not None
    assert restored.kept_database.name.startswith("gym.db.before-restore-")
    assert marks(restored.kept_database) == ["in the backup", "after the backup"]
    assert restored.kept_reports is not None
    assert restored.kept_reports.name.startswith("reports.before-restore-")
    assert len(folder_files(restored.kept_reports)) == 2
    assert not restored.needs_upgrade
    assert not Path("gym.db.restoring").exists()


@pytest.mark.usefixtures("backup_password")
def test_a_new_server_with_no_database_gets_the_backup(
    backup_password: bytes,
) -> None:
    mark("in the backup")
    backup = backups.make()
    stop_the_apps()
    Path("gym.db").unlink()

    restored = restore(backup, backup_password)

    assert marks() == ["in the backup"]
    assert restored.kept_database is None
    assert restored.kept_reports is None
    assert Path("reports").is_dir()


def refused(backup: Path, password: bytes, match: str) -> None:
    """The restore is refused and nothing changed."""
    before = Path("gym.db").read_bytes()
    with pytest.raises(RestoreRefusedError, match=match):
        restore(backup, password)
    assert Path("gym.db").read_bytes() == before
    assert not list(Path().glob("*before-restore*"))
    assert not Path("gym.db.restoring").exists()


@pytest.mark.usefixtures("backup_password")
def test_a_wrong_password_is_refused() -> None:
    backup = backups.make()
    stop_the_apps()

    refused(backup, b"another-password-" + b"y" * 20, "wrong backup password")


@pytest.mark.usefixtures("backup_password")
def test_a_missing_file_is_refused() -> None:
    refused(Path("backups/gym-backup-2026-01-01-000000.zip"), b"x", "no backup at")


@pytest.mark.usefixtures("backup_password")
def test_a_backup_encrypted_with_another_key_is_refused(
    monkeypatch: pytest.MonkeyPatch, backup_password: bytes
) -> None:
    backup = backups.make()
    stop_the_apps()
    use_database_key(monkeypatch, OTHER_KEY)
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", PASSWORD)

    with pytest.raises(RestoreRefusedError, match="can't be opened with"):
        restore(backup, backup_password)
    assert not list(Path().glob("*before-restore*"))


@pytest.mark.usefixtures("backup_password")
def test_a_backup_from_newer_code_is_refused(
    alembic_config: Config, add_test_migration: AddMigration, backup_password: bytes
) -> None:
    # The backup's database ran a migration this code doesn't have.
    add_test_migration("def upgrade() -> None:\n    pass\n")
    command.upgrade(alembic_config, "head")
    backup = backups.make()
    stop_the_apps()

    refused(backup, backup_password, "doesn't know")


@pytest.mark.usefixtures("backup_password")
def test_a_backup_from_older_code_needs_an_upgrade(
    alembic_config: Config, add_test_migration: AddMigration, backup_password: bytes
) -> None:
    backup = backups.make()
    # The code moved on since: a new migration, already run.
    add_test_migration("def upgrade() -> None:\n    pass\n")
    command.upgrade(alembic_config, "head")
    stop_the_apps()

    restored = restore(backup, backup_password, alembic_config)

    assert restored.needs_upgrade


@pytest.mark.usefixtures("backup_password")
def test_a_database_in_use_is_refused(backup_password: bytes) -> None:
    backup = backups.make()
    stop_the_apps()
    app = sqlcipher.connect("gym.db")
    try:
        key = get_settings().database_key_hex
        assert key is not None
        apply_key(app, key)
        app.execute("SELECT count(*) FROM sqlite_master").fetchone()

        refused(backup, backup_password, "in use")
    finally:
        app.close()


@pytest.mark.usefixtures("backup_password")
def test_a_zip_with_unexpected_files_is_refused(backup_password: bytes) -> None:
    backup = backups.make()
    stop_the_apps()
    # Someone added a file that would land outside the reports folder.
    with pyzipper.AESZipFile(backup, "a", encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(backup_password)
        archive.writestr("reports/../../evil.txt", b"made up")

    refused(backup, backup_password, "unexpected file")
    assert not Path("../evil.txt").exists()


@pytest.mark.usefixtures("backup_password")
def test_a_leftover_from_an_earlier_run_is_refused(backup_password: bytes) -> None:
    backup = backups.make()
    stop_the_apps()
    Path("gym.db.restoring").mkdir()

    with pytest.raises(RestoreRefusedError, match="already exists"):
        restore(backup, backup_password)


@pytest.mark.usefixtures("backup_password")
def test_the_command_asks_for_the_password_and_says_what_it_did(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backup = backups.make()
    stop_the_apps()
    monkeypatch.setattr("sys.argv", ["restore_backup", str(backup)])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: PASSWORD)

    restore_backup.main()

    printed = capsys.readouterr().out
    assert "Restored the backup made" in printed
    assert "gym.db.before-restore-" in printed
    assert PASSWORD not in printed


@pytest.mark.usefixtures("backup_password")
def test_the_command_says_nothing_changed_when_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = backups.make()
    stop_the_apps()
    monkeypatch.setattr("sys.argv", ["restore_backup", str(backup)])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "a-wrong-password")

    with pytest.raises(SystemExit, match="Nothing was changed"):
        restore_backup.main()


@pytest.mark.usefixtures("backup_password")
def test_a_backslash_in_a_report_name_is_refused(backup_password: bytes) -> None:
    backup = backups.make()
    stop_the_apps()
    # A backslash separates folders on Windows.
    with pyzipper.AESZipFile(backup, "a", encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(backup_password)
        archive.writestr(r"reports/a\..\..\evil.txt", b"made up")

    refused(backup, backup_password, "unexpected file")


@pytest.mark.usefixtures("backup_password")
def test_an_unreadable_database_is_set_aside_with_its_wal(
    backup_password: bytes,
) -> None:
    mark("in the backup")
    backup = backups.make()
    stop_the_apps()
    # The current database is broken, and left a WAL beside it.
    Path("gym.db").write_bytes(b"broken" * 100)
    Path("gym.db-wal").write_bytes(b"a WAL from the broken database")
    Path("gym.db-shm").write_bytes(b"its index")

    restored = restore(backup, backup_password)

    assert not Path("gym.db-wal").exists()
    assert not Path("gym.db-shm").exists()
    assert marks() == ["in the backup"]
    assert restored.kept_database is not None
    kept_wal = restored.kept_database.with_name(restored.kept_database.name + "-wal")
    assert kept_wal.read_bytes() == b"a WAL from the broken database"


@pytest.mark.usefixtures("backup_password")
def test_a_failed_swap_puts_everything_back(
    backup_password: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    mark("in the backup")
    backup = backups.make()
    mark("after the backup")
    Path("reports").mkdir()
    (Path("reports") / "report-2026-11.pdf").write_bytes(b"made-up November")
    stop_the_apps()
    real_move = shutil.move

    def move(source: Path, target: Path) -> object:
        if Path(target).name == "reports":
            raise OSError("the disk is full")
        return real_move(source, target)

    monkeypatch.setattr(shutil, "move", move)

    with pytest.raises(OSError, match="disk is full"):
        restore(backup, backup_password)

    assert marks() == ["in the backup", "after the backup"]
    assert folder_files(Path("reports")) == {"report-2026-11.pdf": b"made-up November"}
    assert not list(Path().glob("*before-restore*"))
