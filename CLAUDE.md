# Gym Check-In & Subscription System

A check-in and subscription system for a real local gym. It runs on the gym's front-desk PC and will be used in production. It is also a portfolio project.
Claude writes the code. The developer (the user) supervises: approves plans, makes the architectural and product decisions, and reviews the work at the architecture level (decision 0012).

## Project status
- Design doc: `Gym Check-In & Subscription System — Design Doc.md` in the project root (the source of truth; read the relevant section before starting a milestone)
- Current milestone: 1 — Foundation, split into eight features (decisions 0008, 0014, 0020): ~~project setup~~ → ~~settings (`.env`)~~ → ~~database foundation~~ → ~~settings table~~ → ~~staff accounts & permissions~~ → ~~first-run setup & staff sessions~~ → ~~activity log~~ → **frontend foundation**.
- Done: project setup (uv, ruff, pytest, pre-commit with gitleaks + ruff, GitHub Actions CI, admin/public apps with `/health`, README); settings (`.env`): `app/core/config.py` (`get_settings()`), `GYM_*` env vars / `.env`, validated at app startup, `.env.example` (decision 0013); database foundation: SQLite engine + `DbSession` (`app/core/db.py`), `UTCDateTime` + `Base` (`app/core/models/`), `utc_now`/`to_local` (`app/core/clock.py`), Alembic with FK-safe migrations and an empty baseline, shared startup that refuses an out-of-date DB (`app/core/startup.py`), `/migration` skill (decision 0015); settings table: `settings` key/value table, `GymSettings` with `load_gym_settings()`, `load_gym_settings_for_editing()` (settings screen only) and `update_gym_settings()` in `app/core/gym_settings.py` (decision 0016); staff accounts & permissions: `staff_users` table, Argon2id PINs (`app/core/pins.py`), `Role`/`Permission` and the one `ROLE_PERMISSIONS` map with `has_permission()` (`app/core/permissions.py`), staff-account service with the last-manager guard and the PIN lockout (`check_pin()` in `app/core/staff.py`) (decisions 0017, 0018); first-run setup & staff sessions: `/setup` for the gym name and first manager, the lock screen (`/login`, `/lock`, placeholder `/` in `app/admin/auth.py`), `staff_sessions` table and service (`app/core/staff_sessions.py`, lock time per role: managers 5 min, instructors 60, 12-hour cap), `CurrentStaff` / `require_permission` (`app/admin/security.py`), CSRF origin check + signed token (`app/admin/csrf.py`, `GYM_SECRET_KEY`), host guard on the admin app, `staff_page()` (decision 0019); activity log: append-only `activity_log` table (triggers refuse UPDATE/DELETE), `record()` with the `Action`/`Target` enums in `app/core/activity_log.py`, the staff functions and `update_gym_settings()` take the actor as `by=` and log what they change, `create_first_manager()` and `check_gym_settings()` for first-run setup, logins not logged, customers archive-only (`customers.delete` removed) (decision 0021).
- Next feature: **frontend foundation** (decision 0020). Vite + React + TypeScript in `frontend/` with separate admin and public builds, FastAPI serving the built files, the Vite dev proxy, TypeScript types generated from OpenAPI, a Node job in CI, and setup, login and home rebuilt in React with JSON routes. Decide how the CSRF token reaches the React app. Remove Jinja2 and the templates once nothing uses them, and update the README stack line. New libraries beyond those named in 0020 need the developer's OK.
- Follow-ups:
  - Relative `GYM_DATABASE_PATH` and the `.env` lookup depend on the process's working directory. A missing DB file now stops startup, but the two apps could still open different files if started from different folders. Pin a base folder or require absolute paths in prod (milestone 6 / hosting).
  - Packaging (milestone 6): the apps need `alembic.ini` and `migrations/` next to the code at runtime (the startup check reads them).
  - Settings screen (milestone 4): load with `load_gym_settings_for_editing()`, convert form fields to their types before `update_gym_settings()`, and require a manager-only permission on the server. SMTP host/user and the backup folder become settings in milestones 5/6 (after hosting). Email addresses are ASCII-only for now (decision 0016).
  - Activity log (decision 0021): every later feature adds its actions to `Action` and calls `record()` from its core functions; opening a health form's contents is logged too (milestone 3). The log screen (milestone 4, `activity_log.view`) must cope with older before/after shapes. Confirm with the manager that keeping customer data (no deletion on request) is fine before launch. A migration that rebuilds `activity_log` must re-create its two triggers.
  - Code review leftovers from the activity log (low priority): a `/setup` race raises `SetupAlreadyDoneError` as a 500 instead of a 404; the append-only triggers live only in the migration, not the model (a `create_all` schema would lack them); the `log()` test helper and `FAKE_HASH` are copied across test files (belong in `tests/conftest.py`); setup validates the gym name twice.
  - Code review leftovers (low priority): two migration heads give Alembic's raw error at startup instead of `DatabaseNotReadyError`; the naive-datetime checks test `tzinfo is None` rather than `utcoffset() is None`; the `both_apps` test marker is duplicated in `test_apps.py` and `test_startup.py`.
  - If "database is locked" shows up in practice, switch write requests to `BEGIN IMMEDIATE` in `app/core/db.py` (decision 0015).
  - Starlette warns that `httpx` for `TestClient` is deprecated in favour of `httpx2`. Look into it; swapping needs the developer's OK.
  - Nothing stops an app being started on `0.0.0.0`. Add a guard in the start script / service config (milestone 6, after hosting).
  - Add branch protection on `main` requiring the "Lint and test" and "Scan for secrets" checks (CI has run on PR #1, so they can be selected now). Remove this line once it's set up.
  - Dependabot for the SHA-pinned GitHub Actions (milestone 6).
  - Hosting follow-ups for staff sessions (decision 0019): if the admin app moves behind HTTPS on a real hostname, change `ALLOWED_HOSTS` in `app/admin/main.py` and add `Secure` to the `gym_staff` cookie. Prod needs `GYM_SECRET_KEY` (both apps and `alembic`).
  - Lock screen (milestone 4): style it, add the role-filtered menus (in React, after the frontend foundation). A polling dashboard doesn't count as activity, so instructors still lock after 60 idle minutes; the manager can raise `instructor_lock_screen_minutes`. Confirm the lock times with the manager.
  - Code review leftovers from staff sessions (low priority): a huge `?staff=` id on `/login` (beyond SQLite's 64-bit range) gives a 500 instead of "not found"; the test helpers (`Clock`, `FAKE_PIN_HASH`, `fast_hashing`, `SAME_ORIGIN`) are copied across six test files and belong in `tests/conftest.py`.
  - Check-in (milestone 3): an instructor's manual check-in with no plan for the month records single entry; only the manager picks or changes plans (decision 0017). The change-plan route decides whether a single-entry → monthly correction covers the visits already made.
  - The instructor/manager permission split is still the design doc's proposal; the manager confirms it (one-line change in `ROLE_PERMISSIONS` plus its test).
- Milestones: 1 Foundation → 2 Customers, prices & plans → 3 Phone linking & check-in → 4 Admin screens → 5 Report → 6 Operations
- **Open: hosting.** A free server may replace the gym-PC + tunnel setup. Don't build anything host-specific until this is decided.
- **Health form** (design doc "Health form" section, decision 0004). Built into the system, filled in on the phone with a signature, stored with a PDF snapshot and an expiry date. It is **blocking**: no check-in (phone or manual) without a valid form, because the gym isn't insured without one. Instructors see only valid / not valid; the full form is for the manager.
- **Upcoming: punch cards** (12 entries for a fixed price). Details are pending, so don't build them yet, but don't design anything that would block adding them later.
- **Styling: milestone 4, with the `frontend-design` skill.** Until then screens stay plainly styled. In milestone 4, `frontend-design` designs the look once (shared layout, styling approach, Hebrew font, colours) and applies it to every screen, admin and customer, including milestone 3's phone pages. It works within the React + TypeScript stack (decision 0020) and must handle Hebrew RTL; customer pages are mobile-first.

## Tech stack
- Python 3.12 + FastAPI, SQLite (`gym.db`, WAL mode)
- SQLAlchemy 2.x (ORM, 2.1 in use) + Alembic (migrations); conventions in decision 0015
- SQLCipher encrypts the whole database file (added in milestone 6; plain SQLite until then). No field-level encryption.
- Decision records: `docs/decisions/`. Check them before changing anything they cover.
- Frontend (decision 0020): React + TypeScript, built with Vite, TanStack Query for data; types generated from FastAPI's OpenAPI spec (`openapi-typescript`). One project in `frontend/`, two builds (admin and public). FastAPI serves the built files from the same domain, so production needs no Node at runtime. Customer pages are mobile-first. Routing: React Router. The typed client is `openapi-fetch`; `openapi-typescript` runs on TypeScript 6 through an npm `overrides` entry (it still declares TypeScript 5). npm (`frontend/.npmrc`: exact versions, no package under 7 days old, no install scripts).
- API: JSON under `/api/...` with Pydantic request/response schemas. Not a separate API server: each FastAPI app serves its own React build and its own API.
- **UI language: Hebrew, right-to-left** (`<html lang="he" dir="rtl">` in both React builds' `index.html`); the code, comments and commits stay in English
- Tooling: uv (packages), ruff (lint + format), pytest (tests), GitHub Actions (CI), pre-commit (gitleaks + ruff, plus ESLint and Prettier for `frontend/`). Rules, hooks and SHA pinning: decision 0011. CI's "Frontend checks" job runs `npm ci`, type-check, lint, format check, both builds and the API types drift check.
- Reports: openpyxl (Excel) + fpdf2 with an embedded Hebrew font (PDF, RTL). Not WeasyPrint.
- Config: `pydantic-settings` reads deployment config from env vars / `.env` into `app/core/config.py` (decision 0013); manager-editable values go in the `settings` table
- **Secrets have a home now:** whatever host runs the apps (gym PC or a server) always has an env / secrets file. A feature that needs a secret (a signing key, a password) adds it to `config.py` as a `SecretStr` read from `GYM_*` env vars / `.env`, required in prod, with a placeholder and a generator command in `.env.example`. Never treat "where secrets live" as a blocker or a reason to avoid a design that needs a key. Only the production *store* (plain env file vs the OS secret store via `keyring`) waits on the hosting decision, and moving between them only changes how `config.py` gets the value.
- Other: `argon2-cffi` (staff PIN hashing, decision 0018), `keyring` (secrets), `pyzipper` (encrypted backups), `tzdata` (needed for `zoneinfo` on Windows)
- One codebase, two app instances: admin on `127.0.0.1:8000`, public on `127.0.0.1:8001` (exposed via Cloudflare Tunnel)
- Layout: `app/core` (db, models, plan/price rules, reports, email), `app/admin`, `app/public`, `frontend/` (React, from the frontend foundation feature), `tests/`

## Implementation notes
- Use plain `def` routes, not `async def`, because SQLite and SQLAlchemy are synchronous.
- **Thin routes:** a route checks permissions, validates input with its Pydantic schema, calls `app/core` and returns the result. Business rules live only in `app/core`, never in routes or React components.
- Routes get the database by declaring a `db: DbSession` parameter (`app/core/db.py`): one transaction per request, committed before the response is sent, rolled back on any exception. Never use `Depends(get_db)` directly: FastAPI's default would commit after the response (decision 0015).
- Get "now" from `app.core.clock.utc_now()` and display times with `to_local()`. Timestamp columns are `Mapped[datetime]` (stored as `UTCDateTime`); naive datetimes are refused.
- The apps never create or migrate the database; they refuse to start unless it's at the newest migration.
- Every admin API route except `/api/lock-screen`, `/api/login`, `/api/setup` and `/health` declares `CurrentStaff` or `require_permission(Permission.X)` (`app/admin/security.py`); forgetting it leaves the route open. Not logged in is a 401 `NotLoggedIn`. The one other exception is the SPA catch-all (`app/core/spa.py`, `serve_frontend()`, registered last), which serves the same data-free `index.html` to everyone.
- Admin API: routes in `app/admin/api/`, request/response shapes in `app/admin/api/schemas.py` (response models extend `Answer`), errors as codes (Hebrew text lives in React). Every `/api` response is `no-store`. After changing a route or schema, run `npm run api:types --prefix frontend` and commit `frontend/src/admin/backend/schema.d.ts`; CI fails if it's out of date.
- React talks to the API only through `frontend/src/admin/backend/client.ts`, which sends the CSRF token as `X-CSRF-Token` (decision 0019; the server accepts only the header). The token comes from `GET /api/session` or the login/setup answer and lives in memory only. `session.tsx` runs the auto-lock timer and sends any 401 to the lock screen. No source folder under `frontend/src/<app>/` may be named `api` (Vite serves source from the site root and proxies `/api/`).
- Admin test clients use `base_url="http://127.0.0.1:8000"` (the host guard refuses `testserver`), and POSTs need a matching `Origin` header.
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
- Never bind either app to `0.0.0.0`. Never register admin routes on the public app, and never put admin screens or admin API calls in the public React build.
- Every permission is checked on the server, using named permissions (e.g. `prices.edit`) mapped to roles in one place. Hiding a button is never the only protection.
- The customer login lives only in the server-set `gym_device` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`, 1 year). Never use `localStorage`, `sessionStorage` or IndexedDB, and React never reads or stores a login token.
- Tokens, link codes and PINs are stored only as hashes (SHA-256 for tokens and codes, Argon2id for PINs, decision 0018).
- Money is always integer agorot, never floats. Timestamps are stored in UTC and shown in Israel time.
- History is never overwritten. Plan corrections add a new row, prices have `valid_from_month`, and past reports must regenerate identically.
- Every staff change writes to `activity_log` (who, what, before, after) through `app/core/activity_log.record()`, in the same transaction. The core function making the change takes the acting staff member as `by=` and records it; logins aren't logged. The log is append-only (triggers refuse UPDATE/DELETE) and never holds PINs, hashes or tokens (decision 0021).
- Customers are archived, never deleted; their data and log history stay (decision 0021).
- Secrets (SMTP password, encryption keys) are read from environment variables or a secret store, never written in code, the DB or the repo. They're read through `app/core/config.py` from env vars / the host's `.env` (see Tech stack); only the production secret store depends on the hosting decision.
- **The repo is public.** Real customer data lives only in the database: never in tests, fixtures, examples, logs or screenshots. Use made-up data.
- **Nothing gym-specific in code** (one installation per gym, see decision 0006): the gym's name, domain, emails and prices come from settings.

## Conventions
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- Branches: `feature/<name>`, `fix/<name>`
- Record important technical decisions in `docs/decisions/` (context → options → decision)
- Testing priorities: report calculation, subscription status logic, and the linking/cookie flow get the most tests

## Commands
- Install: `uv sync` and `npm ci --prefix frontend` (the pre-commit hooks need both), then once per clone `pre-commit install` (pre-commit itself: `uv tool install pre-commit`)
- Build the frontend (both apps serve it; a missing build is a 503 page): `npm run build --prefix frontend`
- Frontend dev server with the `/api` proxy: `npm run dev:admin --prefix frontend` (127.0.0.1:5173 → 8000) / `dev:public` (5174 → 8001)
- Frontend checks: `npm run typecheck`, `lint`, `format:check` (each with `--prefix frontend`)
- Regenerate the API types after changing an `/api` route or schema: `npm run api:types --prefix frontend`
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
