"""Database access: one SQLAlchemy engine per process, and one session
(transaction) per request.

Both apps open the same SQLite file. WAL mode lets the other app keep
reading while one writes; ``busy_timeout`` makes a second writer wait for
the first instead of failing straight away.
"""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from app.core.config import get_settings

# How long a write waits for another app's write to finish before giving
# up with "database is locked". Requests should hold a write for far less.
BUSY_TIMEOUT_MS = 5000


def create_db_engine(path: Path) -> Engine:
    """An engine for the SQLite file at ``path``, with our pragmas applied
    to every connection it opens. The file is created if it doesn't exist."""
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _on_connect)
    event.listen(engine, "begin", _on_begin)
    return engine


def _on_connect(dbapi_connection: SQLiteConnection, _record: Any) -> None:
    # Python's sqlite3 module starts transactions on its own, and only
    # before writes, so a request's reads would run outside its transaction.
    # Turn that off; _on_begin starts every transaction instead (the recipe
    # in SQLAlchemy's SQLite docs, "Serializable isolation / Savepoints").
    dbapi_connection.isolation_level = None

    cursor = dbapi_connection.cursor()
    # WAL: readers don't block the writer and the writer doesn't block
    # readers, so the two apps can share the file.
    cursor.execute("PRAGMA journal_mode=WAL")
    # SQLite ignores foreign keys unless this is on, per connection.
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    # NORMAL is safe with WAL: a power cut can lose the last commits but
    # never corrupts the file. FULL would fsync on every commit.
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _on_begin(connection: Any) -> None:
    connection.exec_driver_sql("BEGIN")


@lru_cache
def get_engine() -> Engine:
    """The engine for this process, built once from the deployment config.

    Tests call ``get_engine.cache_clear()`` (after disposing the old one).
    """
    return create_db_engine(get_settings().database_path)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: a session whose transaction covers the request.

    Commits when the route returns, rolls back if it raises (including an
    ``HTTPException``), so a request's changes are saved all or nothing.
    """
    with Session(get_engine()) as session, session.begin():
        yield session
