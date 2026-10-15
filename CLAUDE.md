# Gym Check-In & Subscription System

A check-in and subscription system for a real local gym. It runs on the gym's front-desk PC and will be used in production. It is also a portfolio project.
The developer (the user) must understand every part of the codebase. Claude is a helper, not the owner.

## Project status
- Design doc: `Gym Check-In & Subscription System — Design Doc.md` in the project root (the source of truth; read the relevant section before starting a milestone)
- Current milestone: 1 — Foundation (not started). Planning is done: design doc updated, decisions 0001–0007 recorded, local git repo created (nothing committed yet).
- Next feature: project setup (uv project, ruff, pytest, gitleaks pre-commit, GitHub Actions CI), followed by the first commit.
- Milestones: 1 Foundation → 2 Customers, prices & plans → 3 Phone linking & check-in → 4 Admin screens → 5 Report → 6 Operations
- **Open: hosting.** A free server may replace the gym-PC + tunnel setup. Don't build anything host-specific until this is decided.
- **New requirement: health form** (not in the design doc yet). Built into the system, filled in on the phone with a signature, stored with a PDF snapshot and an expiry date. It is **blocking**: no check-in (phone or manual) without a valid form, because the gym isn't insured without one. Instructors see only valid / not valid; the full form is for the manager.
- **Upcoming: punch cards** (12 entries for a fixed price). Details are pending, so don't build them yet, but don't design anything that would block adding them later.

## Tech stack
- Python 3.12 + FastAPI, SQLite (`gym.db`, WAL mode)
- SQLAlchemy 2.0 (ORM) + Alembic (migrations)
- SQLCipher encrypts the whole database file (added in milestone 6; plain SQLite until then). No field-level encryption.
- Decision records: `docs/decisions/`. Check them before changing anything they cover.
- Server-rendered Jinja2 HTML + HTMX for interactivity (customer pages mobile-first), no build step
- **UI language: Hebrew, right-to-left** (`<html lang="he" dir="rtl">`); the code, comments and commits stay in English
- Tooling: uv (packages), ruff (lint + format), pytest (tests), GitHub Actions (CI)
- Reports: openpyxl (Excel) + fpdf2 with an embedded Hebrew font (PDF, RTL). Not WeasyPrint.
- Other: `keyring` (secrets), `pyzipper` (encrypted backups), `tzdata` (needed for `zoneinfo` on Windows)
- One codebase, two app instances: admin on `127.0.0.1:8000`, public on `127.0.0.1:8001` (exposed via Cloudflare Tunnel)
- Layout: `app/core` (db, models, plan/price rules, reports, email), `app/admin`, `app/public`, `tests/`

## Implementation notes
- Use plain `def` routes, not `async def`, because SQLite and SQLAlchemy are synchronous.
- The admin app needs CSRF protection (FastAPI doesn't include it).
- Run uvicorn with a single worker, so scheduled jobs (report, backups) never run twice.
- Behind Cloudflare, the client IP is in `CF-Connecting-IP`, not the socket address. Use that header for rate limiting.

## Workflow
One feature = one branch = one PR = **one Claude session**. New sessions don't remember earlier ones; they rely on this file, the design doc, `docs/decisions/` and git history.

1. Start a **new session** and run `/start-feature <feature>`: read the docs, plan, approve, create the branch.
2. For each step: build (Claude, or the developer in hint mode) → review → **commit**.
3. Run `/finish-feature`: check the whole branch (tests, lint, gitleaks, `/code-review`), fix, and update the Project status above.
4. Commit the wrap-up, push, open a PR, and merge into `main`. Close the session.

Use `/explain-changes` any time to understand code, and `/decision` to record a technical choice. Subagents are only for side jobs inside a session (searching, research), never for building a feature. Work on one feature at a time.

## How we work
- **Explain non-trivial code.** After writing anything beyond boilerplate, briefly explain what it does and why it is built that way.
- **Ask before architectural decisions.** Don't choose libraries, change the database schema, change the folder structure or change route contracts without asking first. Suggest options and give a recommendation.
- **Keep changes small and focused.** Do one feature or fix at a time, so each change can be reviewed and committed on its own.
- **Never commit or push** unless asked.
- **"Hint mode":** when I say a feature is mine to write, give hints, reviews and pointers only, never the full solution.
- **If the code and the design doc disagree, stop and ask.** Don't silently pick one.

## Protected areas (ask before touching)
- Staff auth: PINs, lock screen, roles and permissions
- Customer login: link codes, device sessions, the `gym_device` cookie
- Plan, price and report calculation logic
- Database schema & migrations

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
- Admin: `uvicorn app.admin.main:app --host 127.0.0.1 --port 8000`
- Public: `uvicorn app.public.main:app --host 127.0.0.1 --port 8001`
- Phone testing tunnel: `cloudflared tunnel --url http://127.0.0.1:8001`
- (fill in once the project is set up: install, test, lint)
