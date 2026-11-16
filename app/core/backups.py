"""Encrypted backups (design doc: "Security and backups", decision 0047).

A backup is one zip file in the backups folder, ``gym-backup-<local date
and time>.zip``, encrypted with AES-256 and the backup password
(``GYM_BACKUP_PASSWORD``). It holds:

- ``gym.db``: a consistent copy of the database, made with SQLite's backup
  API while the apps keep running (never a plain file copy, which could
  catch a write half-done). The copy is made through connections keyed with
  ``GYM_DATABASE_KEY``, so it stays encrypted with that key: a restore
  needs both the backup password and the database key.
- ``reports/``: the monthly reports' Excel and PDF files.
- ``manifest.json``: when the backup was made and the migration its
  database is at, so a restore can refuse one the code doesn't know.

A backup is written under a temporary name, reopened and checked, and only
then given its real name, so a file with the real name is always complete.
The backups folder is the only record of backups: no table, so restoring
an older backup can't roll back the record of the newer ones.

Nothing here is logged in the activity log: no staff member makes a backup.
"""

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pyzipper
import sqlcipher3.dbapi2 as sqlcipher

from app.core.clock import to_local, utc_now
from app.core.config import get_settings
from app.core.db import BUSY_TIMEOUT_MS, apply_key

logger = logging.getLogger(__name__)

# The names inside a backup.
DATABASE_NAME = "gym.db"
REPORTS_FOLDER = "reports"
MANIFEST_NAME = "manifest.json"

# Bumped if what's inside a backup ever changes shape.
FORMAT = 1

FILE_PREFIX = "gym-backup-"
FILE_SUFFIX = ".zip"
# Local time, to the second: a backup at startup and the evening's can fall
# in the same day, and two restarts in the same minute shouldn't collide.
TIME_FORMAT = "%Y-%m-%d-%H%M%S"
# What a backup's name looks like; anything else in the folder is ignored
# (and never deleted).
_NAME = re.compile(
    re.escape(FILE_PREFIX) + r"(\d{4}-\d{2}-\d{2}-\d{6})" + re.escape(FILE_SUFFIX)
)

# Keeping old backups: the newest of each of the KEEP_DAYS most recent days
# that have one, plus the newest of every calendar month (both local time),
# for good. Everything else is deleted. By day, not "the 30 newest", so an
# app restarted over and over (a backup each start) can't push out the
# days before it.
KEEP_DAYS = 30

# Besides one at every startup, a backup is due once a day from this local
# time on (the job checks hourly, so it's made within the hour after).
DAILY_AT = time(22, 0)

# The dashboard's card turns red after this long without a backup.
OVERDUE_AFTER = timedelta(days=2)

# Left behind only if the process dies mid-backup; never a real backup.
PARTIAL_SUFFIX = ".partial"


class BackupError(RuntimeError):
    """A backup couldn't be made or read; the message says why."""


@dataclass(frozen=True)
class Manifest:
    """What a backup says about itself."""

    made_at: datetime
    # The database's Alembic revision, or None if it was never migrated.
    migration: str | None
    # Whether gym.db inside is SQLCipher-encrypted (False only in dev).
    encrypted: bool


def file_name(made_at: datetime) -> str:
    """The backup's file name, from the local time it was made."""
    return f"{FILE_PREFIX}{to_local(made_at).strftime(TIME_FORMAT)}{FILE_SUFFIX}"


def make() -> Path:
    """Make a backup now and return its path.

    Raises ``BackupError`` if no backup password is set (dev only) or the
    backup fails; nothing is left behind under a backup's name then.
    """
    settings = get_settings()
    if settings.backup_password is None:
        raise BackupError("GYM_BACKUP_PASSWORD isn't set: backups are off")
    password = settings.backup_password.get_secret_value().encode()
    key = settings.database_key_hex
    made_at = utc_now()
    folder = settings.backups_dir
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / file_name(made_at)
    if target.exists():
        raise BackupError(f"{target.resolve()} already exists")
    partial = target.with_name(target.name + PARTIAL_SUFFIX)

    # The database copy goes in a working folder beside the backups (same
    # disk), removed whatever happens. In prod the copy is encrypted.
    work = Path(tempfile.mkdtemp(prefix=".backup-", dir=folder))
    try:
        copy = work / DATABASE_NAME
        migration = _copy_database(settings.database_path, copy, key)
        manifest = Manifest(made_at=made_at, migration=migration, encrypted=bool(key))
        _write_zip(partial, password, copy, settings.reports_dir, manifest)
        read_manifest(partial, password, test_every_file=True)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    logger.info("backup made: %s", target.name)
    return target


def read_manifest(
    path: Path, password: bytes, *, test_every_file: bool = False
) -> Manifest:
    """Open the backup at ``path`` with ``password`` and return its
    manifest. With ``test_every_file``, every file inside is read through
    and checked against its checksum too (slower: the whole backup).

    Raises ``BackupError`` for a wrong password or a damaged or foreign
    file, with the same message for both kinds of wrong password.
    """
    try:
        with pyzipper.AESZipFile(path) as backup:
            backup.setpassword(password)
            names = set(backup.namelist())
            if MANIFEST_NAME not in names or DATABASE_NAME not in names:
                raise BackupError(f"{path.name} isn't a backup of this system")
            if test_every_file and backup.testzip() is not None:
                raise BackupError(f"{path.name} is damaged")
            data = json.loads(backup.read(MANIFEST_NAME))
    except BackupError:
        raise
    except RuntimeError as error:
        # pyzipper's "Bad password for file" (and a file not encrypted with
        # AES, which this system never makes).
        raise BackupError(f"wrong backup password for {path.name}") from error
    except (pyzipper.BadZipFile, OSError, ValueError, KeyError) as error:
        raise BackupError(f"{path.name} is damaged or isn't a backup") from error
    if data.get("format") != FORMAT:
        raise BackupError(f"{path.name} was made by another version of the system")
    return Manifest(
        made_at=datetime.fromisoformat(data["made_at"]),
        migration=data["migration"],
        encrypted=data["encrypted"],
    )


@dataclass(frozen=True)
class SavedBackup:
    """A backup in the backups folder, known by its file name."""

    path: Path
    made_at: datetime  # UTC


def saved() -> list[SavedBackup]:
    """The backups in the backups folder, oldest first, read from their file
    names (the files aren't opened)."""
    folder = get_settings().backups_dir
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = _NAME.fullmatch(path.name)
        if match is None or not path.is_file():
            continue
        try:
            local = datetime.strptime(match[1], TIME_FORMAT)
        except ValueError:  # e.g. a 13th month
            continue
        made_at = local.replace(tzinfo=get_settings().tz).astimezone(UTC)
        found.append(SavedBackup(path=path, made_at=made_at))
    return sorted(found, key=lambda backup: backup.made_at)


def latest(now: datetime) -> SavedBackup | None:
    """The newest backup made by ``now``, or None if there's none yet.

    A backup dated after ``now`` doesn't count: its name came from a clock
    that was ahead (say, at boot before the time synced). Counted, it would
    stop the evening backups and keep the card green until that date."""
    found = [backup for backup in saved() if backup.made_at <= now]
    return found[-1] if found else None


@dataclass(frozen=True)
class BackupStatus:
    """Where backups stand, for the dashboard's backup card."""

    # False only in dev without a backup password: no backups are made.
    configured: bool
    last_backup_at: datetime | None  # UTC
    # No backup at all, or none for OVERDUE_AFTER: the card turns red.
    overdue: bool


def status(now: datetime) -> BackupStatus:
    """Where backups stand at ``now``."""
    newest = latest(now)
    made_at = newest.made_at if newest else None
    return BackupStatus(
        configured=get_settings().makes_backups,
        last_backup_at=made_at,
        overdue=made_at is None or now - made_at > OVERDUE_AFTER,
    )


def is_due(now: datetime) -> bool:
    """Whether the evening's backup is due at ``now``: no backup was made
    since the most recent ``DAILY_AT`` (local time)."""
    newest = latest(now)
    if newest is None:
        return True
    local_now = to_local(now)
    day = local_now.date()
    if local_now.time() < DAILY_AT:
        day -= timedelta(days=1)
    last_due = datetime.combine(day, DAILY_AT, tzinfo=get_settings().tz)
    return newest.made_at < last_due


def prune() -> list[Path]:
    """Delete the backups that aren't kept: all but the newest of each of
    the ``KEEP_DAYS`` most recent days that have one, and the newest of each
    calendar month. Returns what was deleted. Files that aren't backups are
    left alone."""
    found = saved()
    newest_of_day: dict[date, Path] = {}
    newest_of_month: dict[tuple[int, int], Path] = {}
    for backup in found:  # oldest first, so the newest of each wins
        local = to_local(backup.made_at)
        newest_of_day[local.date()] = backup.path
        newest_of_month[(local.year, local.month)] = backup.path
    recent_days = sorted(newest_of_day)[-KEEP_DAYS:]
    keep = {newest_of_day[day] for day in recent_days}
    keep |= set(newest_of_month.values())
    deleted = []
    for backup in found:
        if backup.path not in keep:
            backup.path.unlink()
            deleted.append(backup.path)
    if deleted:
        logger.info("old backups deleted: %d", len(deleted))
    return deleted


def _copy_database(source: Path, copy: Path, key: str | None) -> str | None:
    """Copy the live database into ``copy`` with SQLite's backup API, check
    the copy, and return its Alembic revision."""
    if not source.is_file():
        raise BackupError(f"no database at {source.resolve()}")
    origin = sqlcipher.connect(str(source))
    target = sqlcipher.connect(str(copy))
    try:
        if key is not None:
            # Both keyed with the same key: the pages are copied as they
            # are, so the copy stays encrypted.
            apply_key(origin, key)
            apply_key(target, key)
        origin.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        # One step (pages=-1, the default): the copy is one consistent
        # snapshot. In WAL mode the apps keep writing meanwhile.
        origin.backup(target)
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("the database copy failed SQLite's integrity check")
        # SQLCipher's own check (every page's HMAC). No rows means ok.
        if (
            key is not None
            and target.execute("PRAGMA cipher_integrity_check").fetchall()
        ):
            raise BackupError("the database copy failed SQLCipher's page check")
        return _migration(target)
    except sqlcipher.DatabaseError as error:
        raise BackupError(f"the database couldn't be copied: {error}") from error
    finally:
        target.close()
        origin.close()


def _migration(connection: sqlcipher.Connection) -> str | None:
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
    ).fetchone()
    if not has_table:
        return None
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def _write_zip(
    path: Path,
    password: bytes,
    database: Path,
    reports: Path,
    manifest: Manifest,
) -> None:
    with pyzipper.AESZipFile(
        path,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as backup:
        backup.setpassword(password)
        backup.setencryption(pyzipper.WZ_AES, nbits=256)
        # An encrypted database doesn't compress: stored as it is, which
        # saves running deflate over the whole file for nothing.
        backup.write(
            database,
            DATABASE_NAME,
            compress_type=(
                pyzipper.ZIP_STORED if manifest.encrypted else pyzipper.ZIP_DEFLATED
            ),
        )
        if reports.is_dir():
            for report in sorted(reports.iterdir()):
                # A report being written right now is a .partial file
                # (report_generation._save); its finished file comes next time.
                if report.is_file() and not report.name.endswith(PARTIAL_SUFFIX):
                    backup.write(report, f"{REPORTS_FOLDER}/{report.name}")
        backup.writestr(
            MANIFEST_NAME,
            json.dumps(
                {
                    "format": FORMAT,
                    "made_at": manifest.made_at.isoformat(),
                    "migration": manifest.migration,
                    "encrypted": manifest.encrypted,
                }
            ),
        )
