# 0009. A `/health` route on both apps

- Status: Accepted
- Date: 2026-10-21

## Context
The project-setup feature creates the admin and public FastAPI apps before any real feature exists. Tests and CI need something real to check from the start, and once the system is hosted (gym PC or server, still open), something will need to check that each app is up.

## Options
- **`GET /health` on both apps, returning `{"status": "ok"}`**: gives the smoke tests a real request to make, and works later for uptime checks. Cons: the first route on the public app, which is reachable from the internet.
- **No routes yet**: tests only check that both apps can be imported. Cons: tests prove almost nothing, and a health route would likely be added later anyway.

## Decision
`GET /health` on both apps, returning `{"status": "ok"}` with status 200.

## Consequences
- Smoke tests and CI can check that each app actually serves requests.
- The public route is reachable through the tunnel, so it must never reveal anything beyond "ok": no version, no database state, no settings.
- It doesn't check the database for now. If a deeper check is wanted later (for example, once the database exists), it stays on the admin app or returns only ok / not ok.
