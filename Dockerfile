# One image for both apps (decision 0052). Compose runs it twice, as
# `admin` and `public`; see compose.yaml. No secrets or data go in it:
# they come from the host's .env and mounted folders at runtime.
#
# Base images are pinned by digest (decision 0011). To update one, look up
# the tag's current digest and replace both together.

# ─── Stage 1: both React builds ─────────────────────────────────────
FROM node:26-trixie-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend

WORKDIR /build/frontend
# .npmrc first: exact versions, no install scripts, the 7-day rule.
COPY frontend/.npmrc frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ─── Stage 2: uv, copied in as a single binary ──────────────────────
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv


# ─── Stage 3: the apps ──────────────────────────────────────────────
FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# Use the image's Python, never a downloaded one; compile bytecode at
# install time, since the app user can't write it later.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# A fixed, unprivileged user: the host's data folders must be writable by
# this uid (10001), and nothing in /app is.
RUN groupadd --system --gid 10001 gym \
    && useradd --system --uid 10001 --gid gym --home-dir /app --no-create-home gym

WORKDIR /app

# Dependencies first, so a code change doesn't reinstall them. uv is
# mounted for this one step, never stored in the image.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project \
    && rm /app/.venv/.lock

COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY app/ ./app/
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/

# Where compose mounts the host's folders (the database, reports and
# backups under /data; the logo under /app/branding, read-only).
RUN mkdir /data && chown gym:gym /data

USER gym

# No default command: compose names each app's uvicorn command, always
# on 127.0.0.1 with one worker.
