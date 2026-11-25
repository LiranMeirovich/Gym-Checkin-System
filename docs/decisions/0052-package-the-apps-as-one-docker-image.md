# 0052. Package the apps as one Docker image, run by Compose on the host network

- Status: Accepted
- Date: 2026-11-17

## Context
Decision 0046 put the system on a dedicated Linux server and left open whether its services are plain systemd units or run under Docker. Decision 0047's feature 5 (server setup) planned systemd services, a deploy routine, the tunnel, SMTP and a setup guide, all waiting for the server. Packaging the apps doesn't need the server, so it can be built now on the dev PC and make server setup shorter: install Docker, copy `.env`, start.

The apps have constraints any packaging must keep: both listen on `127.0.0.1` only and refuse requests arriving from any other address (`LocalOnlyMiddleware`, decision 0050); one uvicorn worker each, so the scheduled job never runs twice (decision 0045); they never create or migrate the database; prod needs absolute database, reports and backups paths; the frontend is built before they start.

## Options
- **Plain systemd units**: a Python and Node toolchain installed on the server, a virtualenv per deploy, a unit file per app. No extra layer, but the server's setup depends on its OS packages, and nothing about it can be tried on the dev PC.
- **Docker, default bridge network**: requests reach the container from the bridge's gateway address, not 127.0.0.1, so the local-only guard refuses every one. Making it work means loosening a hardening check.
- **Docker, host network** (`network_mode: host`): the container shares the server's network, the apps bind `127.0.0.1` exactly as today, and `cloudflared` reaches them the same way.

For where the image is built: **on the server from the git checkout** (no registry, nothing published), or **pushed to a registry from CI** (the repo is public, so the image would be too, unless a private registry is set up).

## Decision
Docker, on the host network, built on the server.
- **One image, both apps.** A multi-stage Dockerfile: a Node stage runs `npm ci` and both React builds; a Python 3.12 slim stage (Debian, glibc new enough for the `sqlcipher3` wheels, decision 0048) runs `uv sync --frozen --no-dev` and copies the code, `alembic.ini`, `migrations/` and the built frontend. It runs as a non-root user. Base images are pinned by digest (decision 0011).
- **No secrets or data in the image.** `.dockerignore` keeps out `.env*`, every database file, `branding/`, `backups/`, `reports/`, `outbox/` and `node_modules`.
- **Compose runs the image twice**, as `admin` and `public`, each one uvicorn worker on `127.0.0.1:8000` / `:8001`, `network_mode: host`, `restart: unless-stopped`, secrets from the host's `.env` (`env_file`), and a healthcheck on `/health`.
- **Data lives on the host**: the database, `reports/`, `backups/` and `branding/` are host folders mounted at fixed absolute paths inside the containers, so rebuilding or replacing the image never touches them.
- **Migrations stay a separate, manual step** (`docker compose run --rm admin alembic upgrade head`), as do restore, the owner PIN reset and encrypt-database; restore and encrypt run after `docker compose stop`.
- **Built on the server** from the checkout; CI only builds the image to catch a broken Dockerfile, and pushes nothing.
- The Docker daemon is a systemd service, so 0046's "services are systemd units" still holds, one level down. Whether `cloudflared` is a third compose service or its own unit is decided in server setup.

## Consequences
- Milestone 6 gains a feature: Docker packaging becomes feature 5; server setup, remote access and the launch checks become 6, 7 and 8 (decision 0047 amended).
- Server setup shrinks to installing Docker, the folders, `.env`, the tunnel, SMTP and the guide; its deploy routine is `git pull`, build, migrate, `up -d`.
- Host networking is Linux-only in practice: Docker Desktop on Windows offers it only as an opt-in setting, and the source address it shows the app may not be 127.0.0.1, so a full browser test may have to wait for Linux (WSL or the server). The local-only guard is not loosened for it.
- Every command on the server runs through `docker compose` (`run` or `exec`); the setup guide lists them.
- Base image digests need occasional bumps for security fixes, like `sqlcipher3`'s bundled OpenSSL.
- Logs go to Docker's log (or the journal); setting up the app's own loggers stays a follow-up.
