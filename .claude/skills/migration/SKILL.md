---
name: migration
description: The strategy for every database schema change - adding, changing or removing a table, column, constraint or index, or migrating existing data. Use whenever a model in app/core/models changes or a new Alembic migration is needed, before writing the migration.
argument-hint: "<the schema change, e.g. 'add the settings table'>"
---

# Change the database schema

Change: $ARGUMENTS

The schema is a protected area (CLAUDE.md) and holds a real gym's data, so every change follows these steps. Background: `migrations/env.py` and its docstring.

## 1. Agree on the change first
- Present the change at the architecture level: tables, columns, types, constraints, foreign keys and what happens to existing rows. Get the developer's OK before writing code.
- Check it against the design doc's Data model and the hard rules: money in integer agorot, timestamps in UTC, history never overwritten (corrections add rows, nothing is updated in place or deleted).
- Point out anything destructive (dropping or renaming a table or column, narrowing a type, a new `NOT NULL` on a table that has rows) and how existing data survives it.

## 2. Change the models
- Models live in `app/core/models/<area>.py`, one module per area. Import each new module in `app/core/models/__init__.py`, or Alembic won't see its tables.
- A `Mapped[datetime]` column is a `UTCDateTime` automatically. Calendar dates (birthdays, form expiry) use `date`.
- Timestamps are always set from Python (`default=utc_now`), never by SQL (`server_default=func.now()`, `CURRENT_TIMESTAMP`): SQL writes a shorter text format that breaks time comparisons. A test enforces this, and data migrations that write timestamps must use the same `YYYY-MM-DD HH:MM:SS.ffffff` UTC format.
- Don't name constraints by hand: the naming convention on `Base.metadata` does it, and batch mode needs those names.
- Declare foreign keys on every relation. Pick `ondelete` deliberately: the system archives and deactivates instead of deleting, so the default (no cascade) is usually right.

## 3. Generate the migration
```bash
uv run alembic revision --autogenerate -m "add settings table"
```
The message is short, lower case and says what changes. The file appears in `migrations/versions/`, dated, and is linted and formatted automatically.

## 4. Review the generated file by hand
Autogenerate is a first draft. Read every line and fix:
- **Renames:** they come out as drop + add, which loses the data. Rewrite them as `batch_op.alter_column(..., new_column_name=...)` or `op.rename_table`.
- **New `NOT NULL` columns on existing tables:** add a `server_default`, or add the column nullable, fill it, then make it `NOT NULL`.
- **Things autogenerate misses:** CHECK constraints, server defaults, changes to enum values. Add them by hand.
- **Data migrations:** write SQL with `op.execute`, or use a small `sa.table()` definition inside the migration. **Never import app models**: they keep changing, and old migrations must keep running exactly as written.
- **`downgrade()`:** must undo `upgrade()`. If an upgrade truly can't be undone (data is gone), raise an error in `downgrade()` that says so, and tell the developer.
- **Foreign keys:** `env.py` turns them off while migrations run and runs `PRAGMA foreign_key_check` before committing. Never change the `foreign_keys` pragma inside a migration, and never "fix" a failed check by deleting rows without the developer's OK.

## 5. Test it
- `uv run pytest`. The migration tests fail if the models and migrations disagree, if there's more than one head, or if a migration can't be undone and re-applied.
- If the change touches tables that already hold rows, add a test that seeds made-up rows at the previous revision, upgrades, and checks the data came through.
- Try it on a dev database: `uv run alembic upgrade head`, then `uv run alembic downgrade -1`, then `upgrade head` again.

## 6. Rules that never bend
- **Never edit a migration that has been merged into `main`.** Someone's database has already run it. Fix it with a new migration.
- **One linear history:** if two branches each add a migration (two heads), re-point the newer one's `down_revision` before merging. Don't use `alembic merge`.
- **Back up before upgrading a production database.** Until automatic backups exist (milestone 6), copy `gym.db` while both apps are stopped.
- No real customer data in migrations, tests or seeds (the repo is public).

## 7. Report it
In the step summary, show the schema change (a table outline is fine) and call out: anything destructive, any data migration, which tables get rebuilt (batch mode), and whether `downgrade()` is a full undo.
