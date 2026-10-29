# Gym Check-In & Subscription System

A check-in and subscription system for a real local gym. It runs on the gym's front-desk PC and will be used in production. It is also a portfolio project.
Claude writes the code. The developer (the user) supervises: approves plans, makes the architectural and product decisions, and reviews the work at the architecture level (decision 0012).

## Project status
- Design doc: `Gym Check-In & Subscription System — Design Doc.md` in the project root (the source of truth; read the relevant section before starting a milestone)
- Current milestone: **2 — Customers, prices & plans**, split into four features (decision 0022): 1 Customers → 2 Prices → 3 Plan choices and monthly status → 4 Plan corrections. Freezes are dropped for now and customer photos left out. Each feature ships core logic, admin JSON routes and a plain React page; styling waits for milestone 4. Milestone 1 (Foundation) is done: all eight features (decisions 0008, 0014, 0020) are merged.
- Done (milestone 1): project setup, settings (`.env`, 0013), database foundation (0015), settings table (0016), staff accounts & permissions (0017, 0018), first-run setup & staff sessions (0019), activity log (0021), frontend foundation (0020). Git history and those decisions have the details.
- Done (milestone 2): customers (0023).
- Key modules: config `app/core/config.py` · DB session `app/core/db.py` · clock `app/core/clock.py` · gym settings `app/core/gym_settings.py` · permissions `app/core/permissions.py` · staff and PINs `app/core/staff.py`, `pins.py` · staff sessions `app/core/staff_sessions.py` · activity log `app/core/activity_log.py` · customers and phone normalising `app/core/customers.py` · startup check `app/core/startup.py` · SPA serving `app/core/spa.py` · auth deps `app/admin/security.py` · CSRF `app/admin/csrf.py` · admin API `app/admin/api/` · React client `frontend/src/admin/backend/client.ts`.
- Next: **feature 2, Prices** (`/start-feature prices`). Read the design doc's "Plans, prices and billing" and "Data model" sections first. Each screen is a JSON route in `app/admin/api/` plus a React page (the customer pages are the pattern to follow); plan, price and report logic is a protected area.
- Follow-ups: `docs/follow-ups.md`, grouped by milestone. Read the current milestone's section and "Any feature" before planning.
- Milestones: 1 Foundation → 2 Customers, prices & plans → 3 Phone linking & check-in → 4 Admin screens → 5 Report → 6 Operations
- **Open: hosting.** A free server may replace the gym-PC + tunnel setup. Don't build anything host-specific until this is decided.
- **Health form** (design doc "Health form" section, decision 0004). Built into the system, filled in on the phone with a signature, stored with a PDF snapshot and an expiry date. It is **blocking**: no check-in (phone or manual) without a valid form, because the gym isn't insured without one. Instructors see only valid / not valid; the full form is for the manager.
- **Upcoming: punch cards** (12 entries for a fixed price). Details are pending, so don't build them yet, but don't design anything that would block adding them later.
- **Styling: milestone 4, with the `frontend-design` skill.** Until then screens stay plainly styled. In milestone 4, `frontend-design` designs the look once (shared layout, styling approach, Hebrew font, colours) and applies it to every screen, admin and customer, including milestone 3's phone pages. It works within the React + TypeScript stack (decision 0020) and must handle Hebrew RTL; customer pages are mobile-first.

## Tech stack
- Python 3.12 + FastAPI, SQLite (`gym.db`, WAL mode)
- SQLAlchemy 2.x (ORM, 2.1 in use) + Alembic (migrations); conventions in decision 0015
- SQLCipher encrypts the whole database file (added in milestone 6; plain SQLite until then). No field-level encryption.
- Decision records: `docs/decisions/`, indexed in `docs/decisions/README.md`. Check them before changing anything they cover.
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
