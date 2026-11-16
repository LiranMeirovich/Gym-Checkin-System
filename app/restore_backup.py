"""Restore a backup (design doc: "Security and backups", decision 0049).

    uv run python -m app.restore_backup backups/gym-backup-2026-11-16-220714.zip

Run on the server with both apps stopped. It asks for the backup password
(``GYM_BACKUP_PASSWORD`` of the install that made the backup) without
showing it. The database inside the backup must open with this install's
``GYM_DATABASE_KEY``.

The backup is checked before anything is replaced: the password opens it,
every file in it matches its checksum, its database opens with the key and
passes SQLite's (and SQLCipher's) integrity checks, and this version of the
code knows its migration. Only then are the files swapped:

- the current database is renamed to ``<name>.before-restore-<time>``
  (with its ``-wal`` and ``-shm`` files, if any),
- the current reports folder to ``<folder>.before-restore-<time>``,
- and the backup's database and reports take their places.

Nothing is deleted here: once the apps run on the restored database and it
looks right, delete the ``.before-restore-`` copies by hand. If the backup
is at an older migration, run ``uv run alembic upgrade head`` before
starting the apps (they refuse to start until then).

Nothing is written to the activity log: the database it would go in is
the one being replaced, and no app is running.
"""

import getpass
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pyzipper
import sqlcipher3.dbapi2 as sqlcipher
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core import backups
from app.core.clock import to_local, utc_now
from app.core.config import get_settings
from app.core.db import apply_key
from app.core.startup import ALEMBIC_INI, DatabaseNotReadyError, check_database_key

# Where the backup is unpacked before the swap, next to the database.
WORK_SUFFIX = ".restoring"
KEPT_INFIX = ".before-restore-"

# SQLite's side files beside a database in WAL mode. Kept with it: a WAL
# left beside the restored file would be replayed into it.
SIDE_SUFFIXES = ("-wal", "-shm")

# What a report's file name inside a backup may look like.
_PLAIN_NAME = re.compile(r"[\w.-]+")


class RestoreRefusedError(RuntimeError):
    """The backup can't be restored as things stand; the message says why.
    Nothing was changed."""


@dataclass(frozen=True)
class Restored:
    manifest: backups.Manifest
    # Where the replaced database and reports folder were moved (None if
    # there was none, as on a new server).
    kept_database: Path | None
    kept_reports: Path | None
    # True if the backup is at an older migration than the code.
    needs_upgrade: bool


def restore(
    backup: Path, password: bytes, alembic_config: Config | None = None
) -> Restored:
    """Check the backup at ``backup`` and swap it in for the current
    database and reports. ``alembic_config`` defaults to the project's
    alembic.ini (tests pass their own)."""
    settings = get_settings()
    database = settings.database_path
    reports = settings.reports_dir
    key = settings.database_key_hex
    if not backup.is_file():
        raise RestoreRefusedError(f"no backup at {backup.resolve()}")
    try:
        manifest = backups.read_manifest(backup, password, test_every_file=True)
    except backups.BackupError as error:
        raise RestoreRefusedError(str(error)) from error
    scripts = ScriptDirectory.from_config(alembic_config or Config(ALEMBIC_INI))
    known = {script.revision for script in scripts.walk_revisions()}
    if manifest.migration not in known:
        raise RestoreRefusedError(
            f"the backup's database is at migration {manifest.migration}, which "
            f"this version of the code doesn't know: restore it with the "
            f"version that made it"
        )

    stamp = to_local(utc_now()).strftime(backups.TIME_FORMAT)
    kept_database = database.with_name(f"{database.name}{KEPT_INFIX}{stamp}")
    kept_reports = reports.with_name(f"{reports.name}{KEPT_INFIX}{stamp}")
    work = database.with_name(database.name + WORK_SUFFIX)
    for leftover in (work, kept_database, kept_reports):
        if leftover.exists():
            raise RestoreRefusedError(
                f"{leftover.resolve()} already exists (from an earlier run?); "
                f"move it away after checking what it is, then run this again"
            )

    work.mkdir(parents=True)
    try:
        restored_database = work / backups.DATABASE_NAME
        restored_reports = work / backups.REPORTS_FOLDER
        _unpack(backup, password, restored_database, restored_reports)
        _check_database(restored_database, key, manifest.migration)
        sides = [
            (
                database.with_name(database.name + suffix),
                kept_database.with_name(kept_database.name + suffix),
            )
            for suffix in SIDE_SUFFIXES
        ]
        # Copied before the in-use check opens the database: SQLite deletes
        # the side files of a database it can't read (a wrong key, a damaged
        # file), and its WAL may hold the last changes.
        copied = []
        try:
            for side, kept_side in sides:
                if side.exists():
                    shutil.copy2(side, kept_side)
                    copied.append((side, kept_side))
            if database.exists():
                _refuse_if_in_use(database, key)
            # Never beside the restored file, where it would be replayed.
            for side, _ in sides:
                side.unlink(missing_ok=True)
            _swap(
                [(database, kept_database), (reports, kept_reports)],
                [(restored_database, database), (restored_reports, reports)],
            )
        except BaseException:
            # Put the side files back where they were (the swap already put
            # the database back), or drop the copies if they're still there.
            for side, kept_side in copied:
                if side.exists():
                    kept_side.unlink()
                else:
                    kept_side.rename(side)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

    return Restored(
        manifest=manifest,
        kept_database=kept_database if kept_database.exists() else None,
        kept_reports=kept_reports if kept_reports.exists() else None,
        needs_upgrade=manifest.migration != scripts.get_current_head(),
    )


def _unpack(backup: Path, password: bytes, database: Path, reports: Path) -> None:
    """Write out the backup's database and reports. Only the names a backup
    has are written, each to a path chosen here, never one from the zip."""
    reports.mkdir()
    with pyzipper.AESZipFile(backup) as archive:
        archive.setpassword(password)
        for name in archive.namelist():
            if name == backups.DATABASE_NAME:
                target = database
            elif name.startswith(f"{backups.REPORTS_FOLDER}/"):
                file_name = name.removeprefix(f"{backups.REPORTS_FOLDER}/")
                # A plain file name only (report-2026-10.xlsx): no "/" or
                # "\" (a separator on Windows), no ":" (a drive), no "..".
                if not _PLAIN_NAME.fullmatch(file_name) or file_name.startswith("."):
                    raise RestoreRefusedError(f"unexpected file in the backup: {name}")
                target = reports / file_name
            elif name == backups.MANIFEST_NAME:
                continue
            else:
                raise RestoreRefusedError(f"unexpected file in the backup: {name}")
            with archive.open(name) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)


def _check_database(path: Path, key: str | None, migration: str | None) -> None:
    try:
        check_database_key(path, key)
    except DatabaseNotReadyError as error:
        raise RestoreRefusedError(f"the backup's database: {error}") from error
    connection = sqlcipher.connect(str(path))
    try:
        if key is not None:
            apply_key(connection, key)
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RestoreRefusedError("the backup's database failed SQLite's check")
        if (
            key is not None
            and connection.execute("PRAGMA cipher_integrity_check").fetchall()
        ):
            raise RestoreRefusedError("the backup's database failed SQLCipher's check")
        found = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlcipher.DatabaseError as error:
        raise RestoreRefusedError(f"the backup's database: {error}") from error
    finally:
        connection.close()
    if found != [(migration,)]:
        raise RestoreRefusedError("the backup's database and manifest disagree")


def _refuse_if_in_use(path: Path, key: str | None) -> None:
    """Refuse while an app has the current database open. Leaving WAL mode
    needs the only connection, so it fails while another is open; it also
    folds the WAL into the file, so the file set aside is complete."""
    connection = sqlcipher.connect(str(path), isolation_level=None)
    try:
        if key is not None:
            apply_key(connection, key)
        connection.execute("PRAGMA busy_timeout=0")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    except sqlcipher.OperationalError as error:  # "database is locked"
        raise RestoreRefusedError(
            f"{path.resolve()} is in use: stop both apps and run this again"
        ) from error
    except sqlcipher.DatabaseError as error:
        # The current database doesn't open with the key: it's still set
        # aside, not deleted, so it can be looked at later.
        if "not a database" not in str(error):
            raise
        return
    finally:
        connection.close()
    if mode != "delete":
        raise RestoreRefusedError(
            f"{path.resolve()} is in use: stop both apps and run this again"
        )


def _swap(set_aside: list[tuple[Path, Path]], put_in: list[tuple[Path, Path]]) -> None:
    """Move each existing ``(current, kept)`` aside, then each
    ``(restored, current)`` into place. If any move fails, everything is
    undone: never half a restore."""
    moved: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    try:
        for current, kept in set_aside:
            if current.exists():
                current.rename(kept)
                moved.append((current, kept))
        for restored, current in put_in:
            # A move, not a rename: the reports folder may be on another
            # disk than the database, where the backup was unpacked.
            shutil.move(restored, current)
            placed.append(current)
    except BaseException:
        for current in placed:
            if current.is_dir():
                shutil.rmtree(current)
            else:
                current.unlink()
        for current, kept in reversed(moved):
            kept.rename(current)
        raise


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: uv run python -m app.restore_backup <backup file>")
    backup = Path(sys.argv[1])
    password = getpass.getpass("Backup password: ").encode()
    try:
        restored = restore(backup, password)
    except RestoreRefusedError as error:
        raise SystemExit(f"Not restored: {error}. Nothing was changed.") from error
    made = to_local(restored.manifest.made_at).strftime("%Y-%m-%d %H:%M")
    print(f"Restored the backup made {made}.")
    for kept in (restored.kept_database, restored.kept_reports):
        if kept is not None:
            print(f"The replaced copy is at {kept.resolve()}: delete it once the")
            print("apps run on the restored data and it looks right.")
    if restored.needs_upgrade:
        print(
            "The backup is at an older migration: run `uv run alembic upgrade "
            "head` before starting the apps."
        )


if __name__ == "__main__":
    main()
