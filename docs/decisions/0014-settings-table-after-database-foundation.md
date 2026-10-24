# 0014. Build the settings table after the database foundation

- Status: Accepted
- Date: 2026-10-24

## Context
Decision [0008](0008-split-milestone-1-into-features.md) put "Settings: configuration from `.env` and the `settings` table" before "Database foundation". But the `settings` table needs the SQLAlchemy engine and Alembic, which arrive in database foundation, and database foundation needs the database path from `.env`. So the two halves of "settings" sit on opposite sides of the database work.

## Options
- **Split settings in two**: `.env` config first, the `settings` table as its own feature right after database foundation. Pros: each feature only uses what already exists. Cons: one more feature and PR.
- **Build both in the settings feature**: Pros: matches 0008 as written. Cons: either part of database foundation gets built early, or the table needs a temporary storage layer that is thrown away later.

## Decision
Split it. Milestone 1's order becomes:

1. Project setup
2. Settings (`.env`): deployment config ([0013](0013-deployment-config-with-pydantic-settings.md))
3. Database foundation
4. Settings table: manager-editable values stored in the database
5. Staff accounts and permissions
6. First-run setup and staff sessions
7. Activity log

## Consequences
- 0008 is amended: its list has one more feature, and the rest of it still applies.
- The `.env` / table boundary: `.env` holds what whoever installs the system sets once (paths, timezone, hostname, mode). The table holds what the manager edits in the UI (gym name, emails, SMTP host and user, backup folder, lock-screen minutes).
- The settings table is a schema change, so it needs the developer's OK when that feature is planned.
