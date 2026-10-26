# 0003. Stack additions: SQLAlchemy, Alembic, HTMX and tooling

- Status: Accepted; the frontend part (Jinja2 + HTMX) is superseded by [0020](0020-react-typescript-frontend-with-a-json-api.md)
- Date: 2026-10-13

## Context
The design doc set the core stack (Python, FastAPI, SQLite, server-rendered HTML, openpyxl) but left some pieces open: how to talk to the database, how to handle migrations, how to add interactivity without a build step, and which development tools to use. Choosing FastAPI ([0001](0001-use-fastapi-for-the-backend.md)) means these don't come built in.

## Options
- **Database access:** SQLAlchemy 2.0 (the standard Python ORM, works with Alembic) / SQLModel (thinner, built on SQLAlchemy, less mature) / raw `sqlite3` (no extra library, but every query and migration by hand).
- **Interactivity:** HTMX (the server returns HTML fragments; no build step) / hand-written `fetch` JavaScript (more code to maintain) / a frontend framework like React (overkill, needs a build step).
- **Tooling:** uv, ruff, pytest and GitHub Actions / pip + flake8 + black (older, slower, more tools to configure).

## Decision
- **SQLAlchemy 2.0** for the ORM and **Alembic** for migrations.
- **Jinja2 templates + HTMX** for the live dashboard, check-in dialog and search. *(Superseded by [0020](0020-react-typescript-frontend-with-a-json-api.md): React + TypeScript with a JSON API.)*
- **uv** (packages), **ruff** (lint + format), **pytest** (tests), **GitHub Actions** (CI on every pull request).
- Supporting libraries: **fpdf2** (PDF with Hebrew), **pyzipper** (encrypted backup zips; the standard `zipfile` can't encrypt), **tzdata** (`zoneinfo` has no time-zone data on Windows), **keyring** (secrets on Windows; may be replaced by environment variables if we move to a server).

## Consequences
- Schema changes always go through Alembic migrations, never by editing the database by hand.
- Every pull request is linted and tested automatically.
- The frontend stays simple, with no build step, but the HTMX patterns need to be learned.
