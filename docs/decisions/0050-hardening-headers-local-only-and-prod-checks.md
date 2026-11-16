# 0050. Hardening: security headers, local-only apps, prod-only checks and the owner PIN command

- Status: Accepted
- Date: 2026-11-16

## Context
Milestone 6's third feature (decision 0047): harden both apps before anything is exposed through the tunnel (decision 0046). The design doc asks the public app for HTTPS-only and no-framing headers and to refuse requests that didn't come through the tunnel's hostname. The follow-ups asked for a content security policy on both React builds, a guard against starting on `0.0.0.0`, absolute paths in prod (relative ones depend on the folder a process starts in) and a way to reset the owner's forgotten PIN, which nobody else may reset (decision 0039).

## Options
- **Refusing `0.0.0.0`**: (a) our own launch command that refuses a non-loopback host: a true "won't start", but only if it's always the one used; (b) a middleware that refuses each request arriving on a non-loopback address: works however uvicorn is started, but the app still starts. uvicorn doesn't tell the app the address it was bound to, so the app itself can't refuse to start.
- **Admin `/docs`**: keep them (they'd break under the CSP anyway: Swagger loads from a CDN and runs an inline script) or turn them off in prod.
- **Public hostname check**: now, from the existing `GYM_PUBLIC_HOSTNAME`, or wait for server setup.
- **Owner PIN reset**: log it as the owner with the existing "PIN reset" action, or add a new "reset from the server" action; require both apps stopped, or allow it while they run.

## Decision
- **Headers on every answer of both apps** (`SecurityHeadersMiddleware`, wrapping all other middleware so refusals get them too): a CSP allowing only the app's own origin (images also `data:` for the signature canvas and `blob:` for PDF and note tabs; `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, a `Permissions-Policy` turning off camera, microphone and location. `Strict-Transport-Security` (one year, no subdomains) in prod only. The health form PDF still opens in Chrome under this policy.
- **Local-only per request** (option b, `LocalOnlyMiddleware`): a request whose connection arrived on any address but `127.0.0.1` / `::1` gets a 403, and the refusal is logged with that address. `cloudflared` connects on 127.0.0.1. A Unix socket passes.
- **Prod only**: the public app answers only to `GYM_PUBLIC_HOSTNAME`, plus `127.0.0.1` / `localhost` for checks on the server (`PublicHostMiddleware`, Starlette's host check built per request); the admin app answers `/docs`, `/redoc` and `/openapi.json` with a 404 (`DocsOnlyInDevMiddleware`). The spec is still built in-process for the frontend's types. Dev `/docs` stays blank under the CSP; nothing uses it.
- **Absolute paths in prod**: `GYM_DATABASE_PATH`, `GYM_REPORTS_DIR` and `GYM_BACKUPS_DIR` must be absolute, checked with the other required prod settings, so every program that loads the config refuses a relative one.
- **`uv run python -m app.reset_owner_pin`**: checks the database, asks for the PIN twice, then calls the existing `staff.reset_pin(..., by=owner)`: the PIN rules, lockout lifted, the owner's sessions ended, logged as the owner. The apps may keep running (one short transaction on the write lock).

## Consequences
- An app started on `0.0.0.0` still starts but serves nothing off the machine; a true refusal to start needs our own launch command (server setup can add one).
- The public app depends on `cloudflared` passing the phone's `Host` on unchanged (its default); confirmed in the launch checks.
- HSTS is hard to undo for a hostname once browsers have seen it; it only takes effect over the tunnel's https.
- New code that needs an outside script, an inline script or style, a frame or a plugin must change the CSP on purpose.
- A shell on the server can take over the owner account; it already holds the database key in `.env`. The log can't tell a command reset from the owner's own.
- `.env` itself is still looked up in the starting folder: the services must set their working folder (server setup).
- The admin app's own hostname, `Secure` cookie and access gate stay with remote access (feature 6).
