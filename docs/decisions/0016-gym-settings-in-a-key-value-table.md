# 0016. Store gym settings in a key/value table, defined in code

- Status: Accepted
- Date: 2026-10-24

## Context
The manager edits some values from the admin app: the gym name, the manager's email, the report recipients and the lock-screen minutes. Decision [0014](0014-settings-table-after-database-foundation.md) put them in a `settings` table, separate from the deployment config in `.env`. This feature had to settle where exactly they live and how they're typed and validated. Both apps run as separate processes and must see a change straight away, every staff change goes in the activity log, and the data must be encrypted and backed up with everything else.

## Options
- **Everything in `.env`**: no new storage, but every change means editing a file on the gym PC and restarting both apps, and the manager can't do it from the app.
- **A settings file the admin app rewrites**: readable and editable by hand. But the app has to write it safely (a half-written file stops startup), both apps have to notice changes, the change and its activity-log row can't be saved together, and the file needs its own encryption and backups.
- **One row, one column per setting**: real column types and database checks, but every new setting is a migration.
- **Key/value rows, with every key defined in code**: one row per setting, the value as JSON text. Types, defaults and validation are in one Pydantic model. A new setting needs no migration, but the database can't check the values.

## Decision
Key/value rows, defined in code. The table is `settings` (`key` primary key, `value` JSON text, `updated_at`). `GymSettings` in `app/core/gym_settings.py` is the one place a setting is defined.

- **A missing row means the default** from the code. The migration adds no rows; settings with no sensible default (gym name, manager email) read as "not set" until first-run setup. Clearing a setting deletes its row, so it follows the default again.
- **Read on every request, never cached**, so a change saved in the admin app reaches the public app immediately.
- **Bad stored data fails loudly.** An unknown key, text that isn't JSON or an invalid value raises an error instead of falling back to the default. The one exception is the settings screen: its loader shows the default for a bad row and reports the problem next to the field, so the manager can save a good value over it.
- **Updates are all or nothing.** Each change is validated on its own, and saved with one insert-or-update statement, so two saves of a new key can't collide. Unchanged values aren't rewritten.
- **Email addresses are plain ASCII.** Commas, angle brackets, quotes and control characters are refused, so a stored address can't add recipients or headers when the report is emailed.
- **Error messages never repeat values**, since they can be email addresses and end up in logs.

## Consequences
- Settings use the database's transactions, encryption and backups, and a change can be saved together with its activity-log row.
- A setting can't be checked by the database itself; tests cover the validation instead.
- Settings are current state, overwritten in place. Anything that must be reproducible later (who a past report was sent to) has to be stored with that record, not read from settings.
- Setting changes aren't logged yet: the activity log arrives in a later milestone 1 feature, which must wire it into `update_gym_settings()`.
- A rule involving two settings would need checking against the stored values; none exists yet.
- Removing or renaming a setting needs a data migration that deletes or re-keys its rows (the `/migration` skill says so); adding one doesn't.
- Saving uses SQLite's `INSERT ... ON CONFLICT`, which ties this code to SQLite (and SQLCipher, which is SQLite).
