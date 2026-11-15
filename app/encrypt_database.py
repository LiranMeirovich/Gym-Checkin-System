"""Encrypt an existing plain database, once (decision 0005).

    uv run python -m app.encrypt_database

Run with both apps stopped, after setting ``GYM_DATABASE_KEY``. The plain
file (``GYM_DATABASE_PATH``) is copied into a new, encrypted file with
SQLCipher's ``sqlcipher_export()``. The copy is checked before anything is
replaced: it opens with the key, passes SQLite's and SQLCipher's integrity
checks, and has the same schema, the same migration and the same number of
rows in every table. Only then are the files swapped: the plain original is
renamed to ``<name>.plain-<date>`` (never deleted here) and the encrypted
copy takes its place.

The renamed original still holds every customer's data, readable by
anyone: delete it once the apps start on the encrypted file.

If the run is cut off between the two renames (a power cut), the database
file is missing and both ``<name>.encrypting`` (the checked, encrypted
copy) and ``<name>.plain-<date>`` (the original) are left. Running this
again says so: renaming the ``.encrypting`` file to ``<name>`` finishes it.

Nothing is written to the activity log: no staff member makes the change
and no app is running. Nothing in the data changes, only how it's stored.
"""

from datetime import date
from pathlib import Path

import sqlcipher3.dbapi2 as sqlcipher

from app.core.clock import local_today
from app.core.config import get_settings
from app.core.db import apply_key, raw_key
from app.core.startup import is_plain_sqlite

# Where the encrypted copy is written before the swap, next to the original.
IN_PROGRESS_SUFFIX = ".encrypting"


class EncryptionRefusedError(RuntimeError):
    """The database can't be encrypted as things stand; the message says why."""


def plain_copy_path(path: Path, today: date) -> Path:
    """Where the plain original is kept after the swap."""
    return path.with_name(f"{path.name}.plain-{today.isoformat()}")


def encrypt_database(path: Path, key: str | None, today: date) -> Path:
    """Encrypt the plain database at ``path`` with ``key`` (64 hex digits)
    and return where the plain original was moved to."""
    if key is None:
        raise EncryptionRefusedError(
            "GYM_DATABASE_KEY isn't set: generate a key (see .env.example), "
            "keep a copy off this machine, and set it first"
        )
    encrypted = path.with_name(path.name + IN_PROGRESS_SUFFIX)
    kept = plain_copy_path(path, today)
    if not path.is_file():
        originals = sorted(path.parent.glob(f"{path.name}.plain-*"))
        if encrypted.is_file() and originals:
            raise EncryptionRefusedError(
                f"no database at {path.resolve()}, but an earlier run stopped "
                f"half-way through swapping the files: {encrypted.resolve()} "
                f"is the checked, encrypted copy and {originals[-1].resolve()} "
                f"the plain original. Rename the first to {path.name} to finish"
            )
        raise EncryptionRefusedError(f"no database at {path.resolve()}")
    if path.stat().st_size == 0:
        raise EncryptionRefusedError(f"{path.resolve()} is empty: nothing to encrypt")
    if not is_plain_sqlite(path):
        raise EncryptionRefusedError(
            f"{path.resolve()} is already encrypted (or isn't a database)"
        )
    for leftover in (encrypted, kept):
        if leftover.exists():
            raise EncryptionRefusedError(
                f"{leftover.resolve()} already exists (from an earlier run?); "
                f"move it away after checking what it is, then run this again"
            )

    try:
        _export(path, encrypted, key)
        _check_copy(path, encrypted, key)
    except BaseException:
        # Never leave a half-made or unchecked copy behind.
        encrypted.unlink(missing_ok=True)
        raise

    path.rename(kept)
    try:
        encrypted.rename(path)
    except OSError:
        # Put the original back where the apps expect it, and drop the copy
        # so running this again starts clean.
        kept.rename(path)
        encrypted.unlink(missing_ok=True)
        raise
    return kept


def _export(path: Path, encrypted: Path, key: str) -> None:
    """Copy the plain database into a new encrypted file."""
    connection = sqlcipher.connect(str(path), isolation_level=None)
    try:
        # Fold the WAL into the file and leave WAL mode, so the original
        # leaves no -wal or -shm file behind to be mistaken for the new
        # file's. The apps switch the new file to WAL on their first connect.
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        except sqlcipher.OperationalError as error:  # "database is locked"
            raise EncryptionRefusedError(
                f"{path.resolve()} is in use: stop both apps and run this again"
            ) from error
        if mode != "delete":
            raise EncryptionRefusedError(
                f"{path.resolve()} is in use: stop both apps and run this again"
            )
        # Bound parameters, so neither the path nor the key is spliced into
        # the SQL. ATTACH can't run inside a transaction, so it comes first;
        # then BEGIN IMMEDIATE keeps any writer out until the copy is made.
        connection.execute(
            "ATTACH DATABASE ? AS encrypted KEY ?", (str(encrypted), raw_key(key))
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("SELECT sqlcipher_export('encrypted')")
        connection.execute("COMMIT")
        connection.execute("DETACH DATABASE encrypted")
    finally:
        connection.close()


def _check_copy(path: Path, encrypted: Path, key: str) -> None:
    """Refuse the copy unless it opens with the key and holds exactly what
    the original does."""
    if is_plain_sqlite(encrypted):
        raise EncryptionRefusedError("the copy came out unencrypted")

    original = sqlcipher.connect(str(path))
    copy = sqlcipher.connect(str(encrypted))
    try:
        apply_key(copy, key)
        if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise EncryptionRefusedError("the copy failed SQLite's integrity check")
        # SQLCipher's own check: every page's HMAC matches. No rows means ok.
        if copy.execute("PRAGMA cipher_integrity_check").fetchall():
            raise EncryptionRefusedError("the copy failed SQLCipher's page check")

        def schema(connection: sqlcipher.Connection) -> list[tuple[str, ...]]:
            return connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "ORDER BY type, name"
            ).fetchall()

        tables = schema(original)
        if schema(copy) != tables:
            raise EncryptionRefusedError("the copy's tables or triggers differ")
        for kind, name, _, _ in tables:
            if kind != "table" or name.startswith("sqlite_"):
                continue
            # Names come from sqlite_master, not from outside; quoted anyway.
            quoted = name.replace('"', '""')
            count = f'SELECT count(*) FROM "{quoted}"'  # noqa: S608
            if copy.execute(count).fetchone() != original.execute(count).fetchone():
                raise EncryptionRefusedError(f"the copy's {name} rows differ")
        if any(name == "alembic_version" for _, name, _, _ in tables):
            version = "SELECT version_num FROM alembic_version"
            if copy.execute(version).fetchall() != original.execute(version).fetchall():
                raise EncryptionRefusedError("the copy's migration differs")
    finally:
        copy.close()
        original.close()


def main() -> None:
    settings = get_settings()
    path = settings.database_path
    try:
        kept = encrypt_database(path, settings.database_key_hex, local_today())
    except EncryptionRefusedError as error:
        raise SystemExit(f"Not encrypted: {error}.") from error
    print(f"{path.resolve()} is now encrypted with GYM_DATABASE_KEY.")
    print(
        f"WARNING: the plain original is at {kept.resolve()} and anyone can "
        f"read it. Delete it once both apps start on the encrypted database."
    )


if __name__ == "__main__":
    main()
