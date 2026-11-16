"""Encrypted backups: what goes in, that it's encrypted, that a failed
backup leaves nothing behind, when one is due and which are kept
(app/core/backups.py)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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


# --- Which backups exist, when one is due, which are kept ---------------

ISRAEL = ZoneInfo("Asia/Jerusalem")


@pytest.fixture
def dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    get_settings.cache_clear()


def local(*args: int) -> datetime:
    """A moment given in Israel time, as UTC."""
    return datetime(*args, tzinfo=ISRAEL).astimezone(UTC)


def saved_at(*moments: datetime) -> list[Path]:
    """Empty files named like backups made at ``moments``."""
    folder = Path("backups")
    folder.mkdir(exist_ok=True)
    paths = []
    for moment in moments:
        path = folder / backups.file_name(moment)
        path.write_bytes(b"made-up backup")
        paths.append(path)
    return paths


@pytest.mark.usefixtures("dev")
def test_saved_reads_backups_from_their_names_oldest_first() -> None:
    newer, older = saved_at(local(2026, 11, 16, 9, 2), local(2026, 11, 15, 22, 7))
    for other in (
        "notes.txt",
        "gym-backup-2026-11-16-090200.zip.partial",
        "gym-backup-2026-13-01-000000.zip",
        "gym-backup-2026-11-16.zip",
    ):
        (Path("backups") / other).write_bytes(b"")

    found = backups.saved()

    assert [backup.path for backup in found] == [older, newer]
    assert found[1].made_at == local(2026, 11, 16, 9, 2)
    assert backups.latest() == found[1]


@pytest.mark.usefixtures("dev")
def test_no_folder_means_no_backups() -> None:
    assert backups.saved() == []
    assert backups.latest() is None


@pytest.mark.usefixtures("dev")
def test_a_backup_is_due_when_there_is_none() -> None:
    assert backups.is_due(local(2026, 11, 16, 10, 0))


@pytest.mark.usefixtures("dev")
@pytest.mark.parametrize(
    ("made", "now", "due"),
    [
        # Made this evening: not due again until tomorrow's 22:00.
        ((2026, 11, 16, 22, 5), (2026, 11, 16, 23, 0), False),
        ((2026, 11, 16, 22, 5), (2026, 11, 17, 21, 59), False),
        ((2026, 11, 16, 22, 5), (2026, 11, 17, 22, 0), True),
        # A startup backup in the morning doesn't stand in for the evening's.
        ((2026, 11, 16, 9, 0), (2026, 11, 16, 21, 59), False),
        ((2026, 11, 16, 9, 0), (2026, 11, 16, 22, 0), True),
        # Made last night after 22:00, checked the next afternoon.
        ((2026, 11, 15, 22, 30), (2026, 11, 16, 15, 0), False),
        # Off for days: due at once.
        ((2026, 11, 10, 22, 30), (2026, 11, 16, 9, 0), True),
    ],
)
def test_the_evening_backup_is_due_from_22_local(
    made: tuple[int, ...], now: tuple[int, ...], due: bool
) -> None:
    saved_at(local(*made))

    assert backups.is_due(local(*now)) is due


@pytest.mark.usefixtures("dev")
def test_the_30_newest_and_the_newest_of_each_month_are_kept() -> None:
    # One every evening from 25 September to 15 November.
    first = local(2026, 9, 25, 22, 0)
    days = (local(2026, 11, 15, 22, 0) - first).days + 1
    paths = saved_at(*(first + timedelta(days=n) for n in range(days)))
    (Path("backups") / "notes.txt").write_bytes(b"not a backup")

    deleted = backups.prune()

    newest_30 = paths[-30:]  # 17 October to 15 November
    end_of_september = paths[5]  # 30 September, the last of its month
    kept = [end_of_september, *newest_30]
    assert sorted(deleted) == sorted(set(paths) - set(kept))
    assert [backup.path for backup in backups.saved()] == kept
    assert (Path("backups") / "notes.txt").exists()


@pytest.mark.usefixtures("dev")
def test_nothing_is_deleted_with_30_or_fewer() -> None:
    first = local(2026, 10, 1, 22, 0)
    saved_at(*(first + timedelta(days=n) for n in range(30)))

    assert backups.prune() == []
    assert len(backups.saved()) == 30
