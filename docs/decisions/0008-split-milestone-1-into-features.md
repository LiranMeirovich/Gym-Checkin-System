# 0008. Split milestone 1 into one-session features

- Status: Accepted, amended by [0014](0014-settings-table-after-database-foundation.md) (feature order)
- Date: 2026-10-21

## Context
The design doc's milestone 1 (Foundation) covers project layout, settings, the schema and migrations, the first manager account, staff accounts with roles and permission checks, the activity log, and the two app entry points. Our workflow is one feature = one branch = one PR = one Claude session, and every change has to stay small enough for the developer to review and understand. All of milestone 1 in one session would mean one huge branch that mixes tooling with protected areas (schema, staff auth).

## Options
- **Milestone 1 as one feature**: matches the design doc's wording. Cons: a very large PR, a session too long to keep in context, and protected-area code reviewed together with boilerplate.
- **Split into features, one session each**: each piece gets its own plan, branch and review. Cons: more PRs, and the order between them matters.

## Decision
Split milestone 1 into these features, built in this order:

1. **Project setup**: uv project, ruff, pytest, pre-commit with gitleaks, GitHub Actions CI, minimal admin and public apps, README.
2. **Settings**: configuration from `.env` and the `settings` table.
3. **Database foundation**: SQLAlchemy engine on SQLite (WAL mode), Alembic, UTC timestamp helpers.
4. **Staff accounts and permissions**: `staff_users`, PIN hashing, the permission-to-role map.
5. **First-run setup and staff sessions**: first manager account, staff login sessions, CSRF protection.
6. **Activity log**.

The design doc's milestones stay as they are; this only breaks milestone 1 into smaller steps. Later milestones will likely be split the same way when they start.

## Consequences
- Each feature starts in a new session with `/start-feature <feature>`, and CLAUDE.md's Project status tracks which one is next.
- Features 4 and 5 touch protected areas and need extra care in review.
- Open before feature 5: the design doc puts the lock screen in milestone 4, but checking permissions in milestone 1 already needs a logged-in staff member. It also mentions both a PIN and an "Unlock" password prompt. Both must be settled before staff sessions are built.
