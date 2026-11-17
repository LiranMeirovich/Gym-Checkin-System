# 0052. Run the apps in Docker, with a CI-built image and the tunnel sharing their network

- Status: Accepted
- Date: 2026-11-17

## Context
Decision 0046 left open whether the server's services run plain under systemd or in Docker. Milestone 6's features 1–4 are done (decision 0047) and the server isn't ready yet, so packaging can be built and tested on the dev PC now. The server needs the SQLCipher library, Python 3.12, the exact locked packages and the frontend build; doing that by hand on the server is slow to repeat and hard to roll back. The hardening rules (decision 0050) say the apps bind to `127.0.0.1` only and refuse requests that don't come from it.

## Options
- **Plain systemd services**: install Python, SQLCipher and Node on the server, build there, one unit per app. Nothing new to learn, but every server (and a second gym, decision 0006) is set up by hand, and a rollback means rebuilding an old commit.
- **Docker Compose**: one image holding everything, three containers (admin, public, `cloudflared`). Same image in CI and on the server; deploys and rollbacks are a tag. Needs care with networking, volumes and secrets.

For the network, inside Docker:
- **Shared network namespace**: the apps and `cloudflared` share one network, so the tunnel reaches the apps on `127.0.0.1` and the 0050 checks stay as they are.
- **A private Docker network**: the apps bind `0.0.0.0` inside their containers and the local-only check is relaxed to trust that network.

## Decision
**Docker Compose on the server.** A new milestone 6 feature, **Docker packaging**, comes before server setup.

- **The image**: a multi-stage `Dockerfile`. A Node stage builds both React builds and is discarded; the final stage is Debian slim with Python 3.12, the SQLCipher library and the packages from `uv.lock`, plus `app/`, `migrations/`, `alembic.ini` and the built frontend. No Node, tests, `.git`, `.env`, data or logo in it. Base images pinned by digest, like the SHA-pinned actions (decision 0011).
- **One image, three containers** in `compose.yaml`: admin and public (each its own `uvicorn` command, one worker), and Cloudflare's `cloudflared` image. Exactly one admin container, so the scheduled report and backup jobs never run twice.
- **Shared network namespace**: public and `cloudflared` join the admin container's network. Both apps still bind `127.0.0.1`; nothing is published on the server; the 0050 checks don't change.
- **`cloudflared` is in the compose file now**, off by default (a Compose profile) until the domain and tunnel token exist (feature 6, server setup).
- **Data and secrets outside the image**: volumes for the database, `reports/`, `backups/` and `branding/`; the `.env` read at start. Absolute container paths satisfy 0050's prod path check.
- **Built by CI**: GitHub Actions builds the image on every PR, and on a merge to `main` pushes it to the GitHub Container Registry tagged with the commit SHA. The server pulls a tag; a rollback is the previous tag (a newer migration still needs a manual downgrade).
- **Commands** (migrations, restore, encrypting a database, resetting the owner's PIN) run as one-off containers with the same volumes, e.g. `docker compose run --rm admin alembic upgrade head`. The apps still refuse to start on an unmigrated database.
- **Development stays on Windows without Docker.** Docker Desktop is only for checking the image and compose file on the PC.

## Consequences
- Milestone 6 becomes eight features: 1–4 done, then **5 Docker packaging** (the Dockerfile, `compose.yaml` with `cloudflared` off, the CI build and push, a full run on the PC with Docker Desktop), **6 server setup** (Docker and LUKS on the server, systemd starting Docker, the deploy routine, the named tunnel, real SMTP, the setup guide), **7 remote access to the admin app**, **8 launch checks**. Amends 0047; settles 0046's open point.
- The image is public on GHCR, which is fine only because it holds no secrets, data or logo: a test in the feature should check that.
- **Opening the apps on the PC** (recommended, for the feature's plan to confirm): a dev-only `compose.dev.yaml` adds a small forwarder (`socat`) inside the shared network namespace, in the place `cloudflared` takes on the server. It listens on a port published only to the PC's `127.0.0.1` (e.g. 8020/8021, clear of the native dev servers) and passes requests to the apps on `127.0.0.1`, so the apps, the local-only check and the admin host check stay unchanged. The server runs `compose.yaml` alone, with no forwarder and no published ports; a CI check keeps it that way. Rejected: publishing the app ports (needs a dev-only loosening of the local-only check) and a free quick tunnel (the admin host check refuses its hostname, and it puts the test app online).
- Left for the feature's plan: which container user and file permissions the volumes use.
- Decision 0005's note that SQLCipher is easier under Linux/Docker now holds in production.
