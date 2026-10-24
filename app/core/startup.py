"""Startup and shutdown shared by both apps.

Everything is checked before the app serves a single request, so a bad
config or an out-of-date database stops uvicorn at startup with a clear
message, instead of failing on some later request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import get_engine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

UPGRADE_HINT = "run `uv run alembic upgrade head` from the project folder"


class DatabaseNotReadyError(RuntimeError):
    """The database is missing or isn't at the newest migration."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The ``lifespan`` both apps pass to ``FastAPI``."""
    get_settings()
    check_database_is_current()
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
