# Gym Check-In & Subscription System

A check-in and subscription system for a single gym. Customers check in by scanning one QR code on the wall with their own phone; staff manage customers, plans and prices from an admin app; and a monthly billing report is generated and emailed automatically.

> **Status:** in development, milestone 1 (Foundation). See the [design doc](<Gym Check-In & Subscription System — Design Doc.md>) for the full plan.

## How it works

- **Wall QR check-in.** A linked phone checks in with one scan. Phones are linked once with a short code from the front desk, and stay logged in through a server-set cookie.
- **Plans chosen by the customer.** At the first check-in of each month, the customer picks monthly, tri-monthly or single entry on their phone.
- **Health form required.** No check-in, by phone or at the desk, without a valid signed health declaration.
- **Staff roles.** Instructors handle desk work; the manager handles prices, plan corrections, reports and settings. Every permission is checked on the server.
- **Monthly report.** Built on the 1st as Excel and PDF, emailed to the manager, and sent on to billing after approval.
- **Hebrew, right-to-left UI.** Code, comments and docs are in English.

## Tech stack

Python 3.12 · FastAPI · SQLite (SQLAlchemy 2 + Alembic) · React + TypeScript (Vite, React Router, TanStack Query) · uv · npm · ruff · ESLint · Prettier · pytest · GitHub Actions

One codebase runs as two apps: an **admin** app for staff (`127.0.0.1:8000`) and a **public** app with only the customer pages (`127.0.0.1:8001`). Admin routes are never registered on the public app. Each app serves its own React build and a JSON API under `/api`; the public build never contains admin code ([decision 0020](docs/decisions/0020-react-typescript-frontend-with-a-json-api.md)).

## Getting started

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 itself) and [Node.js](https://nodejs.org/) 26 LTS.

```bash
uv sync                    # install dependencies into .venv
npm ci --prefix frontend   # install the frontend's exact locked packages
uv tool install pre-commit
pre-commit install         # run gitleaks, ruff, ESLint and Prettier on every commit
```

Create your local config from the template (on Windows PowerShell: `Copy-Item .env.example .env`):

```bash
cp .env.example .env
```

Create the database (and re-run after pulling changes that add migrations). The apps never create or upgrade it themselves, and refuse to start until it's up to date:

```bash
uv run alembic upgrade head
```

Build the frontend (both apps serve these files; re-run after frontend changes):

```bash
npm run build --prefix frontend
```

Run the apps:

```bash
uv run uvicorn app.admin.main:app --host 127.0.0.1 --port 8000
uv run uvicorn app.public.main:app --host 127.0.0.1 --port 8001
```

Never bind either app to `0.0.0.0`.

On a fresh database, open the admin app at `http://127.0.0.1:8000`: it asks for the gym's name and the first manager account (first-run setup). After that it opens on the lock screen: tap your name and enter your PIN. Do this right after installing, since until then anyone at the PC can become the manager.

## Configuration

Deployment config comes from `GYM_`-prefixed environment variables or a `.env` file in the folder the apps are started from. Real environment variables win. [`.env.example`](.env.example) lists every key with a comment. Both apps check the config when they start, and refuse to start if a value is invalid or the `.env` file has an unknown key. A blank value counts as unset. A misspelt *environment variable* can't be detected and is simply ignored, so double-check names set outside `.env` ([decision 0013](docs/decisions/0013-deployment-config-with-pydantic-settings.md)).

| Key | Default | Notes |
| --- | --- | --- |
| `GYM_ENVIRONMENT` | `prod` | `dev` or `prod` |
| `GYM_DATABASE_PATH` | `gym.db` | SQLite file |
| `GYM_TIMEZONE` | `Asia/Jerusalem` | Timezone used to show times; timestamps are stored in UTC |
| `GYM_PUBLIC_HOSTNAME` | none | Bare hostname phones reach the public app on; required in `prod` |
| `GYM_SECRET_KEY` | random per run in `dev` | Signs the admin app's CSRF tokens; at least 32 characters; required in `prod` (both apps and `alembic` read it). Generate with `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### Gym settings

Values the manager edits in the app live in the database's `settings` table instead, one row per key ([decision 0014](docs/decisions/0014-settings-table-after-database-foundation.md), [decision 0016](docs/decisions/0016-gym-settings-in-a-key-value-table.md)). Every key, with its type, default and validation, is defined in `GymSettings` (`app/core/gym_settings.py`); a key with no row uses its default. Adding a setting means adding a field there, with no migration.

| Key | Default | Notes |
| --- | --- | --- |
| `gym_name` | not set | 1–100 characters; filled in at first-run setup |
| `manager_email` | not set | Gets the monthly report to approve |
| `report_recipients` | empty | Get the report after approval |
| `lock_screen_minutes` | `5` | 1–60 minutes without activity before a manager's session locks |
| `instructor_lock_screen_minutes` | `60` | 1–720 minutes without activity before an instructor's session locks |

The SMTP password and other secrets are never stored here.

### Staff logins

Staff log in on the lock screen with a 6–12 digit PIN ([decision 0018](docs/decisions/0018-staff-pins-and-the-permission-map.md)). A session lives in the `gym_staff` cookie and the `staff_sessions` table (token hash only); it ends on Lock, after the role's idle time, after 12 hours, or when the staff member is deactivated. Every admin request that changes something is protected against CSRF by an origin check and a signed per-session token (the React app keeps it in memory and sends it as the `X-CSRF-Token` header), and the admin app answers only to `127.0.0.1` and `localhost` ([decision 0019](docs/decisions/0019-staff-sessions-csrf-and-lock-times.md)).

## Development

```bash
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
```

For frontend work, run the backend as above, then a Vite dev server with live reload; it proxies `/api` to the backend:

```bash
npm run dev:admin --prefix frontend    # http://127.0.0.1:5173 → admin app on 8000
npm run dev:public --prefix frontend   # http://127.0.0.1:5174 → public app on 8001
npm run typecheck --prefix frontend    # TypeScript
npm run lint --prefix frontend         # ESLint
npm run format --prefix frontend       # Prettier
```

The frontend's API types are generated from the backend's Pydantic schemas. After changing an `/api` route or schema, regenerate and commit them:

```bash
npm run api:types --prefix frontend
```

CI runs the Python lint, format check and tests, the frontend type-check, lint, format check, builds and API types check, and a gitleaks scan of the full history on every pull request.

### Database and migrations

The schema lives in SQLAlchemy models in `app/core/models/` and changes only through Alembic migrations in `migrations/versions/`:

```bash
uv run alembic revision --autogenerate -m "add customers"   # draft a migration from model changes
uv run alembic upgrade head                                  # apply it
```

Generated migrations are drafts: review each one by hand (the [`/migration`](.claude/skills/migration/SKILL.md) skill lists what to check). Foreign keys are switched off while migrations run and checked before the upgrade commits, so a schema change can't silently break or cascade-delete related rows ([decision 0015](docs/decisions/0015-database-access-and-migration-conventions.md)). Tests fail if the models and migrations disagree. In production, stop both apps and back up `gym.db` before upgrading.

## Project layout

```
app/core     shared logic: database, models, plan and price rules, reports, email
app/admin    the staff app
app/public   the customer app (phone pages)
frontend/    React + TypeScript: src/admin and src/public build separately
migrations/  Alembic database migrations
tests/
docs/decisions/   decision records: why each technical choice was made
```

## Security and data

This repository is public. It contains no real customer data and no secrets: tests use made-up data, secrets come from environment variables, and gitleaks blocks commits that contain anything that looks like a key. Each gym runs its own installation, configured through settings; nothing gym-specific is in the code. See [decision 0007](docs/decisions/0007-public-repository-rules.md).

## Built with Claude Code

This project is built with [Claude Code](https://claude.com/claude-code) : Claude writes the code, and the developer owns the architecture, the decisions and the review ([decision 0012](docs/decisions/0012-claude-builds-developer-supervises.md)). The working rules and workflow are public: [`CLAUDE.md`](CLAUDE.md) sets the rules, `.claude/skills/` holds the workflow commands (start a feature, record a decision, explain changes, finish a feature), and every significant choice is recorded in [`docs/decisions/`](docs/decisions/).
