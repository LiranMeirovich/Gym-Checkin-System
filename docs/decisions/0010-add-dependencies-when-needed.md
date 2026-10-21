# 0010. Add each dependency in the feature that first uses it

- Status: Accepted
- Date: 2026-10-21

## Context
Decisions [0001](0001-use-fastapi-for-the-backend.md) and [0003](0003-stack-additions.md) chose the libraries for the whole project (SQLAlchemy, Alembic, Jinja2, openpyxl, fpdf2, pyzipper, keyring and more). The project-setup feature has to decide whether to install all of them now or only what it uses.

## Options
- **Install the whole stack up front**: everything is ready. Cons: `uv.lock` lists packages nothing uses, it's unclear which code needs which package, and unused packages still need security updates.
- **Add each library in the feature that first uses it**: project setup adds only FastAPI and uvicorn (plus ruff and pytest for development). Cons: each feature's first step includes a `uv add`.

## Decision
Add each dependency in the feature that first uses it. This doesn't change which libraries were chosen in 0003, only when they're added.

## Consequences
- `pyproject.toml` and `uv.lock` always match the code, and each dependency's commit shows which feature needed it.
- Adding a library already chosen in 0003 doesn't need a new decision. A library that isn't in 0001 or 0003 still needs the developer's OK (and usually a record).
