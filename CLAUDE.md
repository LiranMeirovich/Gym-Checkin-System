# Gym Check-In & Subscription System

A check-in and subscription system for a real local gym. It runs on the gym's front-desk PC and will be used in production. It is also a portfolio project.
Claude writes the code. The developer (the user) supervises: approves plans, makes the architectural and product decisions, and reviews the work at the architecture level (decision 0012).

## Project status
- Design doc: `Gym Check-In & Subscription System — Design Doc.md` in the project root (the source of truth; read the relevant section before starting a milestone)
- Current milestone: 1 — Foundation, split into seven features (decisions 0008, 0014): ~~project setup~~ → ~~settings (`.env`)~~ → ~~database foundation~~ → **settings table** → staff accounts & permissions → first-run setup & staff sessions → activity log.
- Done: project setup (uv, ruff, pytest, pre-commit with gitleaks + ruff, GitHub Actions CI, admin/public apps with `/health`, README); settings (`.env`): `app/core/config.py` (`get_settings()`), `GYM_*` env vars / `.env`, validated at app startup, `.env.example` (decision 0013); database foundation: SQLite engine + `DbSession` (`app/core/db.py`), `UTCDateTime` + `Base` (`app/core/models/`), `utc_now`/`to_local` (`app/core/clock.py`), Alembic with FK-safe migrations and an empty baseline, shared startup that refuses an out-of-date DB (`app/core/startup.py`), `/migration` skill (decision 0015).
- Next feature: settings table, the first real table (decision 0014). Follow the `/migration` skill; the schema needs the developer's OK.
- Follow-ups:
  - Relative `GYM_DATABASE_PATH` and the `.env` lookup depend on the process's working directory. A missing DB file now stops startup, but the two apps could still open different files if started from different folders. Pin a base folder or require absolute paths in prod (milestone 6 / hosting).
  - Packaging (milestone 6): the apps need `alembic.ini` and `migrations/` next to the code at runtime (the startup check reads them).
  - Code review leftovers (low priority): two migration heads give Alembic's raw error at startup instead of `DatabaseNotReadyError`; the naive-datetime checks test `tzinfo is None` rather than `utcoffset() is None`; the `both_apps` test marker is duplicated in `test_apps.py` and `test_startup.py`.
  - If "database is locked" shows up in practice, switch write requests to `BEGIN IMMEDIATE` in `app/core/db.py` (decision 0015).
  - Starlette warns that `httpx` for `TestClient` is deprecated in favour of `httpx2`. Look into it; swapping needs the developer's OK.
  - Nothing stops an app being started on `0.0.0.0`. Add a guard in the start script / service config (milestone 6, after hosting).
  - Add branch protection on `main` requiring the "Lint and test" and "Scan for secrets" checks (CI has run on PR #1, so they can be selected now). Remove this line once it's set up.
  - Dependabot for the SHA-pinned GitHub Actions (milestone 6).
  - Before "first-run setup & staff sessions": settle whether the lock screen belongs in milestone 1 or 4, and PIN vs password (see decision 0008).
- Milestones: 1 Foundation → 2 Customers, prices & plans → 3 Phone linking & check-in → 4 Admin screens → 5 Report → 6 Operations
- **Open: hosting.** A free server may replace the gym-PC + tunnel setup. Don't build anything host-specific until this is decided.
- **Health form** (design doc "Health form" section, decision 0004). Built into the system, filled in on the phone with a signature, stored with a PDF snapshot and an expiry date. It is **blocking**: no check-in (phone or manual) without a valid form, because the gym isn't insured without one. Instructors see only valid / not valid; the full form is for the manager.
- **Upcoming: punch cards** (12 entries for a fixed price). Details are pending, so don't build them yet, but don't design anything that would block adding them later.

## Tech stack
- Python 3.12 + FastAPI, SQLite (`gym.db`, WAL mode)
- SQLAlchemy 2.x (ORM, 2.1 in use) + Alembic (migrations); conventions in decision 0015
- SQLCipher encrypts the whole database file (added in milestone 6; plain SQLite until then). No field-level encryption.
- Decision records: `docs/decisions/`. Check them before changing anything they cover.
- Server-rendered Jinja2 HTML + HTMX for interactivity (customer pages mobile-first), no build step
- **UI language: Hebrew, right-to-left** (`<html lang="he" dir="rtl">`); the code, comments and commits stay in English
- Tooling: uv (packages), ruff (lint + format), pytest (tests), GitHub Actions (CI), pre-commit (gitleaks + ruff). Rules, hooks and SHA pinning: decision 0011
- Reports: openpyxl (Excel) + fpdf2 with an embedded Hebrew font (PDF, RTL). Not WeasyPrint.
- Config: `pydantic-settings` reads deployment config from env vars / `.env` into `app/core/config.py` (decision 0013); manager-editable values go in the `settings` table
- Other: `keyring` (secrets), `pyzipper` (encrypted backups), `tzdata` (needed for `zoneinfo` on Windows)
- One codebase, two app instances: admin on `127.0.0.1:8000`, public on `127.0.0.1:8001` (exposed via Cloudflare Tunnel)
- Layout: `app/core` (db, models, plan/price rules, reports, email), `app/admin`, `app/public`, `tests/`

## Implementation notes
- Use plain `def` routes, not `async def`, because SQLite and SQLAlchemy are synchronous.
- Routes get the database by declaring a `db: DbSession` parameter (`app/core/db.py`): one transaction per request, committed before the response is sent, rolled back on any exception. Never use `Depends(get_db)` directly: FastAPI's default would commit after the response (decision 0015).
- Get "now" from `app.core.clock.utc_now()` and display times with `to_local()`. Timestamp columns are `Mapped[datetime]` (stored as `UTCDateTime`); naive datetimes are refused.
- The apps never create or migrate the database; they refuse to start unless it's at the newest migration.
- The admin app needs CSRF protection (FastAPI doesn't include it).
- Run uvicorn with a single worker, so scheduled jobs (report, backups) never run twice.
- Behind Cloudflare, the client IP is in `CF-Connecting-IP`, not the socket address. Use that header for rate limiting.

## Workflow
One feature = one branch = one PR = **one Claude session**. New sessions don't remember earlier ones; they rely on this file, the design doc, `docs/decisions/` and git history.

1. Start a **new session** and run `/start-feature <feature>`: read the docs, plan, approve, create the branch.
2. For each step: Claude builds → short architecture-level summary → developer OK → **commit**.
3. Run `/finish-feature`: check the whole branch (tests, lint, gitleaks, `/code-review`), fix, and update the Project status above.
4. Commit the wrap-up, push, open a PR, and merge into `main`. Close the session.

Use `/explain-changes` any time for an architecture-level walkthrough of a change, and `/decision` to record a technical choice. Subagents are only for side jobs inside a session (searching, research), never for building a feature. Work on one feature at a time.

## How we work
- **Talk architecture, not code.** Explain changes in terms of components, responsibilities, data flow, boundaries and trade-offs. Don't walk through code line by line; show a snippet only when it carries a decision (a schema, a route contract, a security check) or when asked.
- **Ask before architectural decisions.** Don't choose libraries, change the database schema, change the folder structure or change route contracts without asking first. Suggest options and give a recommendation.
- **Flag what's risky.** In every summary, call out anything surprising, security-relevant or hard to undo, even if it's small.
- **Add a dependency only in the feature that first uses it** (decision 0010).
- **Keep changes small and focused.** Do one feature or fix at a time, so each change can be reviewed and committed on its own.
- **Never commit or push** unless asked.
- **If the code and the design doc disagree, stop and ask.** Don't silently pick one.

## Protected areas (ask before touching)
- Staff auth: PINs, lock screen, roles and permissions
- Customer login: link codes, device sessions, the `gym_device` cookie
- Plan, price and report calculation logic
- Database schema & migrations: every schema change follows the `/migration` skill

## Hard rules (from the design doc)
- Never bind either app to `0.0.0.0`. Never register admin routes on the public app.
- Every permission is checked on the server, using named permissions (e.g. `prices.edit`) mapped to roles in one place. Hiding a button is never the only protection.
- The customer login lives only in the server-set `gym_device` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`, 1 year). Never use `localStorage`, `sessionStorage` or IndexedDB.
- Tokens, link codes and PINs are stored only as hashes (SHA-256 for tokens and codes, bcrypt or argon2 for PINs).
- Money is always integer agorot, never floats. Timestamps are stored in UTC and shown in Israel time.
- History is never overwritten. Plan corrections add a new row, prices have `valid_from_month`, and past reports must regenerate identically.
- Every staff change writes to `activity_log` (who, what, before, after).
- Secrets (SMTP password, encryption keys) are read from environment variables or a secret store, never written in code, the DB or the repo. (Where they're stored depends on the hosting decision.)
- **The repo is public.** Real customer data lives only in the database: never in tests, fixtures, examples, logs or screenshots. Use made-up data.
- **Nothing gym-specific in code** (one installation per gym, see decision 0006): the gym's name, domain, emails and prices come from settings.

## Conventions
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- Branches: `feature/<name>`, `fix/<name>`
- Record important technical decisions in `docs/decisions/` (context → options → decision)
- Testing priorities: report calculation, subscription status logic, and the linking/cookie flow get the most tests

## Commands
- Install: `uv sync`, then once per clone `pre-commit install` (pre-commit itself: `uv tool install pre-commit`)
- Create / upgrade the database (before starting the apps; in prod, stop both apps and back up first): `uv run alembic upgrade head`
- New migration (follow the `/migration` skill): `uv run alembic revision --autogenerate -m "<what changes>"`
- Admin: `uv run uvicorn app.admin.main:app --host 127.0.0.1 --port 8000`
- Public: `uv run uvicorn app.public.main:app --host 127.0.0.1 --port 8001`
- Test: `uv run pytest`
- Lint / format: `uv run ruff check .` / `uv run ruff format .`
- All hooks on every file: `pre-commit run --all-files`
- Secret scan of the branch: `gitleaks git --log-opts="main..HEAD"`
- Phone testing tunnel: `cloudflared tunnel --url http://127.0.0.1:8001`
- Windows note: the Claude desktop app sandboxes `AppData`, so run `uv python install`, `uv tool install` and `pre-commit install` from your own terminal, not through Claude.
