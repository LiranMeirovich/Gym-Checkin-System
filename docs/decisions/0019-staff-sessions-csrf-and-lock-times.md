# 0019. Server-side staff sessions, signed CSRF tokens and per-role lock times

- Status: Accepted
- Date: 2026-10-26

## Context
Every admin action is checked against the logged-in staff member's permissions, so the admin app needs real logins: a first manager on a fresh install, a lock screen, and sessions that end when someone locks or walks away. FastAPI ships no CSRF protection, and the hard rules say login tokens are stored only as hashes. [0008](0008-split-milestone-1-into-features.md) left open whether the lock screen is built now or in milestone 4. Every protected request goes through one dependency, so its shape matters for every later feature.

## Options
- **Lock screen:** a working one now (tap your name, PIN, Lock, auto-lock) / a bare login form now, the lock screen in milestone 4.
- **Sessions:** a server-side `staff_sessions` table holding token hashes / a signed cookie (Starlette's `SessionMiddleware`), which can't be revoked or timed out on the server.
- **CSRF token:** OWASP's synchronizer token (random, stored with the session; it would have to be stored in plain text to be printed into forms) / derived from the session token with no key / OWASP's signed token, `HMAC(server key, session token)` / a library (double-submit cookie).
- **Idle lock:** one time for everyone (the design doc's 5 minutes) / one per role.

## Decision
- **A working lock screen now**, plainly styled. Permission checks need a real login anyway. Milestone 4 adds the polish and the role-filtered menus.
- **Server-side sessions.** The cookie `gym_staff` (HttpOnly, SameSite=Strict, gone when the browser closes) holds 32 random bytes; `staff_sessions` stores only the SHA-256 hash. A session counts while it isn't ended, it's within its role's idle time, it's under 12 hours old, and its staff member is active. Rows are ended, never deleted. One dependency (`CurrentStaff`, or `require_permission(...)` on top of it) loads the staff row fresh on every request, so role changes and deactivation apply from the next click.
- **CSRF in two layers:** every POST/PUT/PATCH/DELETE must come from this app's own `Origin` (plus `Sec-Fetch-Site: same-origin` when sent); logged-in ones must also carry `HMAC-SHA256(GYM_SECRET_KEY, "csrf:" + session token)`, checked by `CurrentStaff`. It's the standard OWASP pattern, needs no storage, and keeps the hash-only rule without an exception. It brings the first secret, `GYM_SECRET_KEY`, into `config.py` (this amends [0013](0013-deployment-config-with-pydantic-settings.md)): every host has an env / secrets file, so a feature that needs a key adds one.
- **A host guard** on the admin app: only `127.0.0.1` and `localhost` are answered, which stops DNS rebinding, most importantly before first-run setup.
- **First-run setup** at `/setup` while no staff account exists: the gym name and the first manager, saved together or not at all. Afterwards it's a 404.
- **Lock times per role**, both gym settings: managers 5 minutes, instructors 60, since instructors mostly watch the desk screen and check people in. Only requests count as activity, on the server and in the page's own timer.

## Consequences
- Prod needs `GYM_SECRET_KEY` (at least 32 characters) for both apps and for `alembic upgrade`. Changing it only breaks forms on pages already open.
- Every protected route must declare `CurrentStaff` or `require_permission`. Forgetting one leaves the route open; milestone 4's "test every manager action as an instructor" is the safety net.
- A refused login must still commit, so the lockout counters stick ([0018](0018-staff-pins-and-the-permission-map.md)).
- An instructor left logged in means whoever is at the desk acts under their name for up to an hour. Locking and logging in as yourself still matter for the activity log.
- If hosting puts the admin app behind HTTPS on a real hostname, the host guard's allow-list changes and the cookie gets `Secure`.
- A polling dashboard (milestone 4) won't keep a session alive.
