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

Python 3.12 · FastAPI · SQLite (SQLAlchemy 2.0 + Alembic) · Jinja2 + HTMX · uv · ruff · pytest · GitHub Actions

One codebase runs as two apps: an **admin** app for staff (`127.0.0.1:8000`) and a **public** app with only the customer pages (`127.0.0.1:8001`). Admin routes are never registered on the public app.

## Getting started

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 itself.

```bash
uv sync                    # install dependencies into .venv
uv tool install pre-commit
pre-commit install         # run gitleaks and ruff on every commit
```

Run the apps:

```bash
uv run uvicorn app.admin.main:app --host 127.0.0.1 --port 8000
uv run uvicorn app.public.main:app --host 127.0.0.1 --port 8001
```

Never bind either app to `0.0.0.0`.

## Development

```bash
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
```

CI runs lint, format check, tests and a gitleaks scan of the full history on every pull request.

## Project layout

```
app/core     shared logic: database, models, plan and price rules, reports, email
app/admin    the staff app
app/public   the customer app (phone pages)
tests/
docs/decisions/   decision records: why each technical choice was made
```

## Security and data

This repository is public. It contains no real customer data and no secrets: tests use made-up data, secrets come from environment variables, and gitleaks blocks commits that contain anything that looks like a key. Each gym runs its own installation, configured through settings; nothing gym-specific is in the code. See [decision 0007](docs/decisions/0007-public-repository-rules.md).

## Built with Claude Code

This project is built with [Claude Code](https://claude.com/claude-code) as a helper, not the owner. The working rules and workflow are public: [`CLAUDE.md`](CLAUDE.md) sets the rules, `.claude/skills/` holds the workflow commands (start a feature, record a decision, explain changes, finish a feature), and every significant choice is recorded in [`docs/decisions/`](docs/decisions/).
