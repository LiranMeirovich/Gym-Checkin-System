"""Database access: one SQLAlchemy engine per process, and one session
(transaction) per request.

Both apps open the same SQLite file. WAL mode lets the other app keep
reading while one writes; ``busy_timeout`` makes a second writer wait for
the first instead of failing straight away.

A request's transaction starts with ``BEGIN IMMEDIATE``, taking the write
lock before its first read (decision 0027). Nearly every request writes
(a logged-in one updates its staff session), and with a plain ``BEGIN`` a
request that read before another committed can't write afterwards: SQLite
fails it with "database is locked" straight away, ``busy_timeout`` or not.
With ``IMMEDIATE`` the second request waits, then reads what the first
saved, so two saves of the same thing get the normal refusal instead of a
500. Other transactions (startup checks, short reads outside a request)
keep a plain ``BEGIN``.
"""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session

from app.core.config import get_settings

# How long a write waits for another app's write to finish before giving
# up with "database is locked". Requests should hold a write for far less.
BUSY_TIMEOUT_MS = 5000

# Execution option: when true, a transaction starts with BEGIN IMMEDIATE.
IMMEDIATE = "gym_begin_immediate"


def create_db_engine(path: Path) -> Engine:
    """An engine for the SQLite file at ``path``, with our pragmas applied
    to every connection it opens. The file is created if it doesn't exist."""
    # URL.create, not an f-string: characters like "#" or "%" in the path
    # would otherwise be read as URL syntax and open a different file.
    engine = create_engine(URL.create("sqlite", database=str(path)))
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
    if connection.get_execution_options().get(IMMEDIATE):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.exec_driver_sql("BEGIN")


@lru_cache
def get_engine() -> Engine:
    """The engine for this process, built once from the deployment config.

    Tests call ``get_engine.cache_clear()`` (after disposing the old one).
    """
    return create_db_engine(get_settings().database_path)


def get_db() -> Iterator[Session]:
    """A session whose transaction covers the request. Routes don't use this
    directly; they declare a ``DbSession`` parameter.

    Commits when the route returns, rolls back if it raises (including an
    ``HTTPException``), so a request's changes are saved all or nothing.
    Starts with ``BEGIN IMMEDIATE`` (see the module docstring).
    """
    engine = get_engine().execution_options(**{IMMEDIATE: True})
    with Session(engine) as session, session.begin():
        yield session


# The one way routes get the database: ``def route(db: DbSession)``.
# scope="function" makes FastAPI finish get_db (commit or roll back) before
# the response is sent. With the default ("request") the commit would run
# after the client already got its response: it could see "saved" for a
# change that then fails to commit, or reload a page before the change lands.
DbSession = Annotated[Session, Depends(get_db, scope="function")]


def get_read_only_db() -> Iterator[Session]:
    """A session for a route that only reads and needs no login: a plain
    ``BEGIN``, so it never takes the write lock and never waits behind a
    write (WAL lets it read the last committed state). Always rolled back.

    SQLite's ``query_only`` is on for the session's connection, so any
    write (ORM or raw SQL) fails at once with "attempt to write a readonly
    database" (a 500) instead of being lost in the rollback. A route that
    touches a staff or device session writes, so it can't use this. Routes
    don't use this directly; they declare a ``ReadOnlyDbSession`` parameter.
    """
    # No IMMEDIATE option on this engine: its transaction is a plain BEGIN.
    with Session(get_engine()) as session:
        session.connection().exec_driver_sql("PRAGMA query_only=ON")
        try:
            yield session
        finally:
            session.rollback()
            # Connections are pooled: hand this one back writable.
            session.connection().exec_driver_sql("PRAGMA query_only=OFF")


# For the few routes that only read the gym's public facts on every page
# load (``GET /api/branding``), so a page load doesn't queue behind a save.
ReadOnlyDbSession = Annotated[Session, Depends(get_read_only_db, scope="function")]
