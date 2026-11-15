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

The driver is SQLCipher's (``sqlcipher3``), not Python's ``sqlite3``, so the
whole file is encrypted (decision 0005). SQLAlchemy keeps its ordinary
SQLite dialect; only the DB-API module changes. With a key, every new
connection gives it first, before anything reads the file. Without one
(dev only; prod requires a key) the file is plain SQLite.
"""

from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import sqlcipher3.dbapi2 as sqlcipher
from fastapi import Depends
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session

from app.core.config import get_settings

# How long a write waits for another app's write to finish before giving
# up with "database is locked". Requests should hold a write for far less.
BUSY_TIMEOUT_MS = 5000

# Execution option: when true, a transaction starts with BEGIN IMMEDIATE.
IMMEDIATE = "gym_begin_immediate"


def create_db_engine(path: Path, key: str | None = None) -> Engine:
    """An engine for the database file at ``path``, with our pragmas applied
    to every connection it opens. The file is created if it doesn't exist.

    ``key`` is the SQLCipher key as 64 hex digits (``Settings.database_key``,
    validated there), or None for a plain file.
    """
    # URL.create, not an f-string: characters like "#" or "%" in the path
    # would otherwise be read as URL syntax and open a different file. The
    # key never goes in the URL (it's applied in the connect listener), so
    # it can't show up in the engine's repr or a log line.
    engine = create_engine(URL.create("sqlite", database=str(path)), module=sqlcipher)
    event.listen(engine, "connect", _connect_listener(key))
    event.listen(engine, "begin", _on_begin)
    return engine


def raw_key(key: str) -> str:
    """``key`` (64 hex digits) in SQLCipher's raw-key form, ``x'...'``: the
    32 bytes are used as they are, with no passphrase stretching (thousands
    of rounds) on each new connection."""
    # Settings allows nothing but 64 hex digits; checked again here, so no
    # other caller can put anything else into the SQL (see apply_key).
    if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
        raise ValueError("the database key must be 64 hex characters")
    return f"x'{key}'"


def apply_key(dbapi_connection: sqlcipher.Connection, key: str) -> None:
    """Give SQLCipher the key: must be the connection's first statement.

    Wrong keys aren't caught here; the first read fails with "file is not
    a database" (see ``app.core.startup``)."""
    # PRAGMA takes no bound parameters, so the key goes into the SQL text:
    # safe only because raw_key() lets nothing but hex digits through.
    dbapi_connection.execute(f'PRAGMA key = "{raw_key(key)}"')


def _connect_listener(
    key: str | None,
) -> Callable[[sqlcipher.Connection, Any], None]:
    def on_connect(dbapi_connection: sqlcipher.Connection, _record: Any) -> None:
        if key is not None:
            apply_key(dbapi_connection, key)
        _on_connect(dbapi_connection)

    return on_connect


def _on_connect(dbapi_connection: sqlcipher.Connection) -> None:
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
    settings = get_settings()
    return create_db_engine(settings.database_path, settings.database_key_hex)


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
    # One connection, held throughout: switching query_only off must reach
    # the same connection it was switched on for. Asking the session for a
    # connection again after its rollback can get a different one from the
    # pool when requests run at once, leaving this one read-only for the
    # next request (which then fails at BEGIN IMMEDIATE).
    # No IMMEDIATE option on this engine: its transaction is a plain BEGIN.
    with get_engine().connect() as connection:
        connection.exec_driver_sql("PRAGMA query_only=ON")
        try:
            with Session(bind=connection) as session:
                yield session
        finally:
            connection.rollback()
            # Connections are pooled: hand this one back writable.
            connection.exec_driver_sql("PRAGMA query_only=OFF")
            connection.rollback()


# For the few routes that only read the gym's public facts on every page
# load (``GET /api/branding``), so a page load doesn't queue behind a save.
ReadOnlyDbSession = Annotated[Session, Depends(get_read_only_db, scope="function")]
