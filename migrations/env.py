"""Alembic's entry point: runs migrations against the configured database.

The database comes from the deployment config (``GYM_DATABASE_PATH``)
through ``create_db_engine``, so migrations get the same pragmas (WAL,
busy timeout) as the apps, with one exception: foreign keys.

Foreign keys are switched off while migrations run, and checked before the
upgrade commits. This is SQLite's documented procedure for schema changes
(https://www.sqlite.org/lang_altertable.html#otheralter): batch mode
changes a table by copying it, dropping the original and renaming the copy,
and with foreign keys on, dropping a table that others point at fails or
(with ON DELETE CASCADE) deletes the rows that point at it. The check at
the end makes sure the migration left no row pointing at nothing; if it
did, the whole upgrade is rolled back. Every app connection still has
foreign keys on. Migration files must never change the pragma themselves
(see the /migration skill).
"""

from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import Connection

from app.core.config import get_settings
from app.core.db import create_db_engine
from app.core.models import Base, MonthColumn, UTCDateTime

config = context.config

# Use alembic.ini's logging when run from the command line, without
# silencing loggers the app (or pytest) has already set up.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    """Write UTCDateTime and MonthColumn columns as plain ``sa.DateTime()``
    and ``sa.Text()`` in migrations.

    The column type in the database is the same either way; UTC and month
    handling happen in Python. This keeps migration files independent of app
    code that may be renamed or moved later.
    """
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    if type_ == "type" and isinstance(obj, MonthColumn):
        return "sa.Text()"
    return False  # Alembic's default rendering for everything else.


def configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=Base.metadata,
        # SQLite can't alter most things in place; batch mode rebuilds the
        # table (copy, drop, rename) instead.
        render_as_batch=True,
        render_item=render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """``alembic upgrade --sql`` would print SQL to run by hand. Refused: a
    printed script runs without the foreign-key handling above, so a table
    rebuild in it could cascade-delete rows."""
    raise RuntimeError(
        "offline migrations (--sql) aren't supported: run "
        "`uv run alembic upgrade head` so foreign keys are handled safely"
    )


def run_migrations_online() -> None:
    engine = create_db_engine(get_settings().database_path)
    try:
        with engine.connect() as connection:
            # Must happen before the transaction starts: inside one, SQLite
            # silently ignores this pragma. The raw driver connection runs
            # it immediately, without SQLAlchemy opening a transaction.
            connection.connection.driver_connection.execute("PRAGMA foreign_keys=OFF")
            # One transaction around the whole upgrade (Alembic assumes
            # SQLite can't do that, but our explicit BEGIN makes it work),
            # so a failing migration or check leaves the database untouched.
            configure(connection=connection, transactional_ddl=True)
            with context.begin_transaction():
                context.run_migrations()
                _check_foreign_keys(connection)
    finally:
        # Drops the pooled connection, so the pragma can't leak to later use.
        engine.dispose()


def _check_foreign_keys(connection: Connection) -> None:
    """Fail (and roll back) if any row points at a row that doesn't exist."""
    problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if problems:
        # Each row: (table, rowid, referenced table, foreign key index).
        details = ", ".join(
            f"{table} row {rowid} -> {parent}" for table, rowid, parent, _ in problems
        )
        raise RuntimeError(f"migration broke foreign keys: {details}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
