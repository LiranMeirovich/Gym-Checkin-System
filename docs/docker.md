# Running with Docker

How the two apps run on the server: one image, started twice by Docker Compose ([decision 0052](decisions/0052-package-the-apps-as-one-docker-image.md)). Development stays on Windows without Docker (README, "Getting started").

This is for a **Linux** host. The services use the host network, so the apps listen on the server's own `127.0.0.1:8000` (admin) and `127.0.0.1:8001` (public), exactly as without Docker, and `cloudflared` reaches them there. Docker Desktop on Windows or a Mac doesn't give containers the host's network by default, so the apps can't be reached from the PC there.

Every command below runs in the checkout's folder, next to `compose.yaml`.

## What lives where

| What | On the host | In the container |
| --- | --- | --- |
| Code and both React builds | the image (`gym:latest`) | `/app` |
| Secrets and the hostname | `.env` next to `compose.yaml` | environment variables |
| Database, `reports/`, `backups/` | `./data` (or `DATA_DIR`) | `/data` |
| The logo | `./branding` (or `BRANDING_DIR`) | `/app/branding`, read-only |

Rebuilding or replacing the image never touches the data. Compose sets the three data paths itself (`/data/gym.db`, `/data/reports`, `/data/backups`); `.env` must not set `GYM_DATABASE_PATH`, `GYM_REPORTS_DIR` or `GYM_BACKUPS_DIR` (compose's values win anyway).

The app runs as uid **10001**, not root, and can write only to `/data`.

## First install

1. Clone the repository and `cd` into it.
2. Create the data folder, owned by the app's user. Without this, Docker creates it owned by root and the apps can't write to it:
   ```bash
   mkdir -p data branding && sudo chown 10001:10001 data
   ```
   To keep the data elsewhere (another disk), put `DATA_DIR=/srv/gym/data` in `.env` (and `BRANDING_DIR` for the logo); the apps ignore those two names.
3. Put the logo in `branding/` if the gym has one (decision 0034).
4. Create `.env` from `.env.example` with prod values: `GYM_ENVIRONMENT=prod`, `GYM_DATABASE_KEY`, `GYM_BACKUP_PASSWORD`, `GYM_SECRET_KEY`, `GYM_PUBLIC_HOSTNAME` and `GYM_SMTP_*`. Leave out the three data paths. Keep a copy of the database key and the backup password off the machine: a restore needs both.
   ```bash
   chmod 600 .env
   ```
5. Build the image, create the database, start both apps:
   ```bash
   docker compose build
   docker compose run --rm admin alembic upgrade head
   docker compose up -d
   ```
6. Check both are healthy (`docker compose ps` shows `healthy` within about a minute), then do the first-run setup in the admin app at once (README, "Getting started").

The Docker service starts at boot and `restart: unless-stopped` brings both apps back with it, so nothing else is needed for reboots.

## Updating

```bash
git pull
docker compose build
docker compose stop
docker compose run --rm admin alembic upgrade head
docker compose up -d
```

The apps refuse to start on a database that isn't at the newest migration, so migrating is never skipped silently. A backup is made at every start of the admin app; for a large update, check `data/backups/` has a recent one before migrating. Old images pile up after updates: `docker image prune` removes them.

## Everyday commands

| To | Run |
| --- | --- |
| See whether both are up | `docker compose ps` |
| Read the logs | `docker compose logs -f admin` (or `public`) |
| Stop / start both | `docker compose stop` / `docker compose up -d` |
| Restart one | `docker compose restart admin` |

## Maintenance commands

These are the same commands as without Docker (CLAUDE.md, "Commands"), run inside a container. They ask for passwords or PINs, so run them from a real terminal.

- **Reset the owner's forgotten PIN** (the apps may keep running):
  ```bash
  docker compose exec admin python -m app.reset_owner_pin
  ```
- **Restore a backup** (both apps stopped; it keeps the replaced files in `data/` as `….before-restore-<time>`):
  ```bash
  docker compose stop
  docker compose run --rm admin python -m app.restore_backup /data/backups/gym-backup-<time>.zip
  docker compose up -d
  ```
- **Encrypt a plain database once** (both apps stopped, after a backup; then delete the `gym.db.plain-<date>` it reports from `data/`):
  ```bash
  docker compose stop
  docker compose run --rm admin python -m app.encrypt_database
  docker compose up -d
  ```

Paths given to these commands are the container's (`/data/...`), not the host's.
