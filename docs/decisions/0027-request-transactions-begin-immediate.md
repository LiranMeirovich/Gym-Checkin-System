# 0027. Request transactions start with BEGIN IMMEDIATE

- Status: Accepted
- Date: 2026-11-03

## Context
Decision 0015 gives every request one transaction, started with a plain (deferred) `BEGIN`. In WAL mode a deferred transaction reads from a snapshot taken at its first read. If another request commits after that, the first one can't write any more: SQLite fails it with "database is locked" straight away, and `busy_timeout` doesn't retry it. The review of plan corrections found this: two saves of the same plan at the same moment give a 500 instead of the normal `choice_replaced` or `month_covered` refusal. Milestone 3's phone double tap makes it likelier. Nearly every request writes, not only POSTs: a logged-in request updates its staff session's `last_seen_at` (`touch()`), GETs included.

## Options
- **Keep deferred `BEGIN`** and catch "database is locked" in the routes: every write route needs it, and the answer is still a retry, not the real refusal.
- **`BEGIN IMMEDIATE` for POST, PUT, PATCH and DELETE only**: reads never wait. But a GET's `touch()` write can still fail the same way.
- **`BEGIN IMMEDIATE` for every request**: the write lock is taken before the first read, so a second request waits (up to `busy_timeout`, 5 s) and then reads what the first saved. Requests from both apps take turns, each holding the lock for milliseconds.

## Decision
**Every request transaction (`get_db()`, so every `DbSession`) starts with `BEGIN IMMEDIATE`.** This was the developer's choice. The engine's `begin` hook reads an execution option (`IMMEDIATE` in `app/core/db.py`) that `get_db()` sets; transactions outside a request (the 401 handler's short read, the startup check, Alembic) keep a plain `BEGIN`.

## Consequences
- Two saves at once give the second the normal refusal, never a 500: the core's checks see the first one's row.
- Requests no longer run their database work side by side. At one front desk plus customers' phones that's milliseconds of waiting; a request that holds the lock for long (a big report, a slow upload) would hold up the rest, so such work belongs outside the request transaction (milestone 5's report job, milestone 3's health-form upload).
- A request still fails with "database is locked" if it waits more than `busy_timeout` (5 s).
- This replaces decision 0015's plain `BEGIN` for requests; the rest of 0015 stands.
