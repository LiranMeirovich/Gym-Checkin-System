"""Startup and shutdown shared by both apps.

Everything is checked before the app serves a single request, so a bad
config or an out-of-date database stops uvicorn at startup with a clear
message, instead of failing on some later request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import sqlcipher3.dbapi2 as sqlcipher
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import apply_key, get_engine
from app.core.http import drop_query_strings_from_access_log

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

UPGRADE_HINT = "run `uv run alembic upgrade head` from the project folder"

ENCRYPT_HINT = (
    "encrypt it once with `uv run python -m app.encrypt_database` (both apps stopped)"
)

# The first 16 bytes of every plain SQLite file. SQLCipher encrypts the
# whole file, header included, so an encrypted one never starts with this.
SQLITE_HEADER = b"SQLite format 3\x00"


class DatabaseNotReadyError(RuntimeError):
    """The database is missing, can't be opened with the configured key, or
    isn't at the newest migration."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The ``lifespan`` both apps pass to ``FastAPI``."""
    get_settings()
    check_database_is_current()
    drop_query_strings_from_access_log()
    yield
    get_engine().dispose()


def check_database_is_current(alembic_config: Config | None = None) -> None:
    """Refuse to start unless the database exists and its schema is exactly
    the newest migration.

    The apps never create or upgrade the database themselves (migrations
    are run by hand, after a backup). A missing file usually means the app
    was started from the wrong folder: connecting would silently create a
    new, empty database there, so the file is checked before connecting.

    ``alembic_config`` defaults to the project's alembic.ini (tests pass
    their own).
    """
    path = get_settings().database_path
    if not path.is_file():
        raise DatabaseNotReadyError(
            f"no database at {path.resolve()}; to create one, {UPGRADE_HINT}"
        )
    check_database_key(path, get_settings().database_key_hex)

    scripts = ScriptDirectory.from_config(alembic_config or Config(ALEMBIC_INI))
    head = scripts.get_current_head()
    with get_engine().connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()

    if current == head:
        return
    if current is None:
        raise DatabaseNotReadyError(
            f"{path.resolve()} has no schema (it was never migrated); {UPGRADE_HINT}"
        )
    if current not in {script.revision for script in scripts.walk_revisions()}:
        # Usually older code started against a database a newer version
        # already upgraded. Running would mean code and schema disagree.
        raise DatabaseNotReadyError(
            f"{path.resolve()} is at revision {current}, which this version of "
            f"the code doesn't know; it was upgraded by a newer version"
        )
    raise DatabaseNotReadyError(
        f"{path.resolve()} is at revision {current}, but the newest is {head}; "
        f"{UPGRADE_HINT}"
    )


def is_plain_sqlite(path: Path) -> bool:
    """Whether the file at ``path`` starts like a plain SQLite database.
    False for an encrypted one, and for anything too short or not SQLite."""
    with path.open("rb") as file:
        return file.read(len(SQLITE_HEADER)) == SQLITE_HEADER


def check_database_key(path: Path, key: str | None) -> None:
    """Refuse a database file that ``key`` can't open, saying why.

    Without this, all three mistakes below fail with SQLite's own "file is
    not a database". A missing or empty file passes: there is nothing to
    open yet (``alembic upgrade`` creates it, encrypted if there's a key).
    Run by the apps' startup check and by ``alembic`` (``migrations/env.py``).
    """
    if not path.is_file() or path.stat().st_size == 0:
        return
    plain = is_plain_sqlite(path)

    if plain and key is not None:
        raise DatabaseNotReadyError(
            f"{path.resolve()} is not encrypted, but GYM_DATABASE_KEY is set; "
            f"{ENCRYPT_HINT}"
        )
    if plain:
        return
    if key is None:
        raise DatabaseNotReadyError(
            f"{path.resolve()} is encrypted (or isn't a database at all), but "
            f"GYM_DATABASE_KEY isn't set"
        )
    # Encrypted, with a key: only reading the file shows whether it's the
    # right one. A connection of its own, so nothing reaches the app's pool.
    connection = sqlcipher.connect(str(path))
    try:
        apply_key(connection, key)
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher.DatabaseError as error:
        raise DatabaseNotReadyError(
            f"{path.resolve()} can't be opened with GYM_DATABASE_KEY: the key "
            f"is wrong, or the file isn't a database"
        ) from error
    finally:
        connection.close()
