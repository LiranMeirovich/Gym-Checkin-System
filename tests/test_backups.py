"""Encrypted backups: what goes in, that it's encrypted, and that a failed
backup leaves nothing behind (app/core/backups.py)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import pyzipper
import sqlcipher3.dbapi2 as sqlcipher
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core import backups
from app.core.backups import BackupError
from app.core.config import get_settings
from app.core.db import apply_key
from app.core.startup import is_plain_sqlite
from tests.conftest import TEST_DATABASE_KEY, use_database_key

# Made up; real passwords never appear in the repo.
PASSWORD = "not-a-real-backup-password-" + "x" * 8


@pytest.fixture
def backup_password(monkeypatch: pytest.MonkeyPatch) -> bytes:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    return PASSWORD.encode()


def head(alembic_config: Config) -> str | None:
    return ScriptDirectory.from_config(alembic_config).get_current_head()


def extract(backup: Path, name: str, into: Path, password: bytes) -> Path:
    with pyzipper.AESZipFile(backup) as archive:
        archive.setpassword(password)
        return Path(archive.extract(name, into))


@pytest.mark.usefixtures("migrated_db")
def test_a_backup_holds_the_encrypted_database_and_a_manifest(
    backup_password: bytes, alembic_config: Config, tmp_path: Path
) -> None:
    made_at = datetime(2026, 11, 16, 20, 7, 14, tzinfo=UTC)
    path = backups.make()

    assert path.parent == Path("backups")
    assert path.name.startswith("gym-backup-") and path.suffix == ".zip"
    # Israel time in the name (UTC+2 in November).
    assert backups.file_name(made_at) == "gym-backup-2026-11-16-220714.zip"

    manifest = backups.read_manifest(path, backup_password, test_every_file=True)
    assert manifest.migration == head(alembic_config)
    assert manifest.encrypted

    database = extract(path, "gym.db", tmp_path / "out", backup_password)
    assert not is_plain_sqlite(database)
    connection = sqlcipher.connect(str(database))
    try:
        apply_key(connection, TEST_DATABASE_KEY)
        version = connection.execute("SELECT version_num FROM alembic_version")
        assert version.fetchall() == [(head(alembic_config),)]
    finally:
        connection.close()


@pytest.mark.usefixtures("migrated_db")
def test_every_file_inside_is_encrypted(backup_password: bytes) -> None:
    path = backups.make()

    with pyzipper.AESZipFile(path) as archive:
        assert archive.infolist()
        for info in archive.infolist():
            assert info.flag_bits & 0x1  # the zip's "encrypted" flag
            # WinZip's AES field (0x9901): version AE-2, "AE", strength 3
            # (AES-256).
            assert b"\x01\x99\x07\x00\x02\x00AE\x03" in info.extra
        # Without the password nothing reads.
        with pytest.raises(RuntimeError):
            archive.read("manifest.json")


@pytest.mark.usefixtures("migrated_db")
def test_the_reports_go_in_but_not_one_being_written(
    backup_password: bytes,
) -> None:
    reports = Path("reports")
    reports.mkdir()
    (reports / "report-2026-10.xlsx").write_bytes(b"made-up excel")
    (reports / "report-2026-10.pdf").write_bytes(b"made-up pdf")
    (reports / "report-2026-11.pdf.partial").write_bytes(b"half written")

    path = backups.make()

    with pyzipper.AESZipFile(path) as archive:
        archive.setpassword(backup_password)
        assert sorted(archive.namelist()) == [
            "gym.db",
            "manifest.json",
            "reports/report-2026-10.pdf",
            "reports/report-2026-10.xlsx",
        ]
        assert archive.read("reports/report-2026-10.pdf") == b"made-up pdf"


@pytest.mark.usefixtures("migrated_db")
def test_a_wrong_password_is_refused(backup_password: bytes) -> None:
    path = backups.make()

    with pytest.raises(BackupError, match="wrong backup password"):
        backups.read_manifest(path, b"another-password-" + b"y" * 20)


def test_a_file_that_isnt_a_backup_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "gym-backup-2026-11-16-220714.zip"
    path.write_bytes(b"not a zip")

    with pytest.raises(BackupError, match="damaged"):
        backups.read_manifest(path, PASSWORD.encode())


def test_dev_without_a_key_backs_up_a_plain_database(
    monkeypatch: pytest.MonkeyPatch,
    alembic_config: Config,
    tmp_path: Path,
) -> None:
    use_database_key(monkeypatch, None)
    command.upgrade(alembic_config, "head")
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", PASSWORD)
    get_settings.cache_clear()

    path = backups.make()

    manifest = backups.read_manifest(path, PASSWORD.encode())
    assert not manifest.encrypted
    database = extract(path, "gym.db", tmp_path / "out", PASSWORD.encode())
    assert is_plain_sqlite(database)


@pytest.mark.usefixtures("migrated_db")
def test_no_backup_password_means_no_backup() -> None:
    with pytest.raises(BackupError, match="GYM_BACKUP_PASSWORD"):
        backups.make()
    assert not Path("backups").exists()


@pytest.mark.usefixtures("migrated_db")
def test_a_successful_backup_leaves_only_the_zip(backup_password: bytes) -> None:
    path = backups.make()

    assert list(Path("backups").iterdir()) == [path]


@pytest.mark.usefixtures("migrated_db")
def test_a_failed_check_leaves_nothing_behind(
    backup_password: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def damaged(*_args: object, **_kwargs: object) -> None:
        raise BackupError("damaged")

    monkeypatch.setattr(backups, "read_manifest", damaged)

    with pytest.raises(BackupError):
        backups.make()
    assert list(Path("backups").iterdir()) == []


def test_a_missing_database_is_refused(backup_password: bytes) -> None:
    with pytest.raises(BackupError, match="no database"):
        backups.make()
    assert list(Path("backups").iterdir()) == []
