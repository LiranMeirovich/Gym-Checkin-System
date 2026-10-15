# 0006. One installation per gym, configured by settings

- Status: Accepted
- Date: 2026-10-14

## Context
The system is built for one gym, but it shouldn't be tied to that gym. It should be clear that another gym could use it without code changes. At the same time, it stores health forms, so data from different gyms must never mix, and we don't want to add a lot of logic for gyms that don't exist yet.

## Options
- **Hard-coded for this gym**: simplest, but the gym's name, domain and emails end up in the code (and in a public repo), and reusing it means editing code.
- **One installation per gym (single-tenant, configurable)**: each gym runs its own app, database and domain. Everything gym-specific comes from settings. Little extra work, and gyms are fully isolated.
- **One system for many gyms (multi-tenant)**: one app and one database, with a `gym_id` on every table and every query. Adding a gym is easy, but it changes the schema, every query, auth and tests. One missing filter would leak one gym's health forms to another gym.

## Decision
One installation per gym. The code knows nothing about a specific gym. Its name, logo, domain, emails, timezone and default prices come from settings (`.env` and the `settings` table). No multi-tenant logic is added.

## Consequences
- **Nothing gym-specific is hard-coded:** no gym name, domain, email address or real price in Python code or templates.
- Adding a gym means a new deployment with its own `.env` and database (a second `docker compose` setup, if we move to a server).
- Each gym's data is physically separate, which is the safest model for health data.
- If many gyms ever want it, moving to multi-tenant is a known, larger migration. We don't pay that cost now.
