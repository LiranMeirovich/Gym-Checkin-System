# 0015. Database access and migration conventions

- Status: Accepted
- Date: 2026-10-24

## Context
The database foundation feature sets patterns every later table and route inherits: how requests use transactions, how timestamps are stored, how and when migrations run, and how SQLite's foreign keys behave during schema changes. Both apps share one SQLite file, it holds a real gym's data, and SQLite can't alter most of a table in place: Alembic's "batch mode" copies the table, drops the original and renames the copy.

## Options
- **Running migrations:** the admin app upgrades the database at startup / migrations run by hand, and both apps refuse to start unless the database is exactly at the newest migration.
- **Foreign keys during migrations:** leave them on, like the apps / turn them off for the migration connection and check them before committing (SQLite's documented procedure).
- **Timestamps:** plain `DateTime` and discipline / a `UTCDateTime` column type that refuses naive datetimes.
- **Transactions:** one per statement (SQLite's default) / one per request, for reads and writes alike.

## Decision
- **Migrations run by hand** (`uv run alembic upgrade head`), never by the apps. At startup both apps refuse to run if the database file is missing, was never migrated, is behind the code or is ahead of it. A missing file is checked before connecting, so starting from the wrong folder no longer creates an empty database.
- **Foreign keys are off only while migrating.** `migrations/env.py` turns them off for its own connection, runs the whole upgrade in one transaction and runs `PRAGMA foreign_key_check` before committing. Any broken reference rolls the whole upgrade back. Every app connection keeps foreign keys on.
- **Timestamps use `UTCDateTime`.** It stores UTC as fixed-width text, refuses naive datetimes (also in comparisons) and reads back aware UTC. Every `Mapped[datetime]` column gets it automatically. "Now" comes from `app.core.clock.utc_now()`.
- **One transaction per request** through the `get_db` dependency: committed when the route returns, rolled back if it raises. Transactions start with an explicit `BEGIN`, so reads are part of them. This keeps multi-step changes, like a change plus its activity-log row, all or nothing.
- Every schema change follows the `/migration` skill (`.claude/skills/migration/SKILL.md`).

The SQLAlchemy version resolved for this feature is 2.1. That's the same 2.x API that [0003](0003-stack-additions.md) chose ("SQLAlchemy 2.0"), not a different library.

## Consequences
- A fresh install, or a fresh clone in dev, needs `uv run alembic upgrade head` before either app starts. In production, stop both apps and back up `gym.db` first.
- A schema change can't silently delete rows through `ON DELETE CASCADE` while a table is rebuilt, or leave rows pointing at nothing.
- A long upgrade holds the write lock for its whole run, so the apps must be stopped while it runs.
- Transactions start as plain (deferred) `BEGIN`. A request that reads and then writes while the other app is writing can fail at once with "database is locked" instead of waiting. If that shows up in practice, write requests can switch to `BEGIN IMMEDIATE` in one place (`app/core/db.py`).
- The apps need `alembic.ini` and `migrations/` next to the code at runtime, which matters for packaging in milestone 6.
