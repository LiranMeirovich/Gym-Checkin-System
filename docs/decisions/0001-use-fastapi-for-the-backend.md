# 0001. Use FastAPI for the backend

- Status: Accepted
- Date: 2026-10-13

## Context
The design doc chose Python 3.12. The app is mostly server-rendered HTML forms and admin screens, with two separate app instances (admin and public) sharing one codebase. We needed to pick the web framework.

## Options
- **FastAPI**: a modern, lightweight framework. Pros: small and explicit, so every part of the app is understood; easy to mount different routes on the admin and public apps; good to learn. Cons: built mainly for APIs, so sessions, CSRF protection, an ORM, migrations and form handling must be added separately.
- **Django**: a "batteries included" framework. Pros: auth, sessions, CSRF, ORM, migrations and forms all built in. Cons: more framework magic to learn and work around, and a custom PIN lock screen and the two-app split go against its defaults.

## Decision
FastAPI. The developer wanted to learn it, and building sessions and permissions by hand on a small app teaches how they actually work.

## Consequences
- We add SQLAlchemy 2.0 + Alembic for the database (see [0003](0003-stack-additions.md)).
- **CSRF protection for the admin app must be added explicitly.** FastAPI doesn't provide it.
- Routes are plain `def`, not `async def`, because SQLite and SQLAlchemy are synchronous.
- Staff sessions and the lock screen are our own code, so they need careful tests.
