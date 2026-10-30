# Follow-ups

Work found during earlier features that wasn't done there. Grouped by when it's due. `/start-feature` reads the section for the current milestone plus "Any feature"; `/finish-feature` adds new items and removes finished ones.

## Any feature
- Activity log (decision 0021): every feature adds its actions to `Action` and calls `record()` from its core functions. A migration that rebuilds `activity_log` must re-create its two triggers.
- If "database is locked" shows up in practice, switch write requests to `BEGIN IMMEDIATE` in `app/core/db.py` (decision 0015).
- Starlette warns that `httpx` for `TestClient` is deprecated in favour of `httpx2`. Look into it; swapping needs the developer's OK.
- `openapi-typescript` has had no release since Feb 2026 and declares TypeScript 5; it runs on TypeScript 6 through an npm `overrides` entry. If it stays unmaintained or breaks on a TypeScript update, consider `@hey-api/openapi-ts` (needs the developer's OK).
- Dev servers: a committable `.claude/launch.json` (admin/public uvicorn + Vite) reading the developer's own `.env`, for one-click previews.
- Add branch protection on `main` requiring the "Lint and test", "Frontend checks" and "Scan for secrets" checks (each can be selected once it has run on a PR). Remove this line once it's set up.
- Refactor (planned, protected area: staff auth): move first-run setup's rules (`create_manager()` in `app/admin/api/setup.py`: PIN check, PIN match, gym-name check, save order) into `app/core` (e.g. a `first_run_setup()` returning field errors), so the route stays thin as CLAUDE.md requires. Carried over from the old Jinja route; behaviour must not change (the `test_admin_api_setup.py` tests pin it).

## Milestone 2: plan choices (from Prices)
- No prices ship with the system, so `price_for()` can return `None`. Choosing a plan must handle a price that isn't set instead of guessing an amount.

## Milestone 3: phone linking & check-in
- Plan page: customers see their own prices. Decide whether they also see the whole price table (a new public route; the developer sees no reason to hide it).
- Check-in: a price that isn't set must not stop a customer training; decide what an instructor's single-entry fallback records then.
- Check-in: an instructor's manual check-in with no plan for the month records single entry; only the manager picks or changes plans (decision 0017). The change-plan route decides whether a single-entry → monthly correction covers the visits already made.
- Opening a health form's contents is logged in the activity log (decision 0021).
- The instructor's check-in screen shows only what check-in needs (name, health form valid or not, plan status), never date of birth, notes or activity-log entries (decision 0023).
- Linking: look the customer up with `find_by_phone()` (`app/core/customers.py`, built for this) and key the wrong-code lockout on the normalised number, so every way of typing one number counts together (decision 0023).

## Milestone 4: admin screens (from Customers)
- Customer list: search, and sorting / filtering by recent check-ins (e.g. who came in the past month), as queries.

## Milestone 4: admin screens
- Role-filtered menus: the Prices page hides its form with `isManager()` from `customers.ts`, a role check in a customer module. Give the screens one helper for this.
- Settings screen: load with `load_gym_settings_for_editing()`, convert form fields to their types before `update_gym_settings()`, and require a manager-only permission on the server. Email addresses are ASCII-only for now (decision 0016).
- Activity log screen (`activity_log.view`) must cope with older before/after shapes.
- Lock screen: style it, add the role-filtered menus in React. A polling dashboard doesn't count as activity, so instructors still lock after 60 idle minutes; the manager can raise `instructor_lock_screen_minutes`.
- The "אין חיבור לשרת" error markup is copied in six screens (setup, lock screen, the three customer pages); make it a shared component.

## Milestones 5–6: report, operations and hosting
- SMTP host/user and the backup folder become settings (after hosting).
- Relative `GYM_DATABASE_PATH` and the `.env` lookup depend on the process's working directory. A missing DB file stops startup, but the two apps could still open different files if started from different folders. Pin a base folder or require absolute paths in prod.
- Packaging: the apps need `alembic.ini` and `migrations/` next to the code at runtime (the startup check reads them), and `npm ci` + `npm run build` must run before they start (a missing build is a 503 page, not a startup error).
- Security headers: the design doc asks the public app for HTTPS-only and no-framing headers; add a content security policy for both React builds too.
- Nothing stops an app being started on `0.0.0.0`. Add a guard in the start script / service config.
- Dependabot for the SHA-pinned GitHub Actions.
- Staff sessions (decision 0019): if the admin app moves behind HTTPS on a real hostname, change `ALLOWED_HOSTS` in `app/admin/main.py` and add `Secure` to the `gym_staff` cookie. Prod needs `GYM_SECRET_KEY` (both apps and `alembic`).

## Before launch: confirm with the manager
- Keeping customer data (no deletion on request) is fine (decision 0021).
- The lock times (managers 5 min, instructors 60).
- The instructor/manager permission split, still the design doc's proposal (one-line change in `ROLE_PERMISSIONS` plus its test). That now includes instructors seeing prices and their history (`prices.view`).
- Enter the real prices on the Prices screen; none ship with the system.

## Code review leftovers (low priority)
- The append-only triggers live only in the migration, not the model (a `create_all` schema would lack them).
- Test helpers copied across test files belong in `tests/conftest.py`: `log()`, `FAKE_HASH`, `Clock`, `FAKE_PIN_HASH`, `fast_hashing`, `SAME_ORIGIN` (also in `test_admin_api_*.py`, now including the customer and price tests), and the `both_apps` marker (`test_apps.py`, `test_startup.py`).
- Setup validates the gym name twice.
- Two migration heads give Alembic's raw error at startup instead of `DatabaseNotReadyError`.
- The naive-datetime checks test `tzinfo is None` rather than `utcoffset() is None`.
- `app/core/spa.py` answers paths whose last segment has a dot with 404, so a future React route with a dot in a parameter would break on reload.
- Lock's network-failure path (always goes to the lock screen) wasn't reproduced by hand.
- The Prices page's Hebrew errors repeat the 24-month and ₪10,000 limits from `app/core/prices.py`; update them together.
- `frontend/` has no test runner, so `shekelsToAgorot()` was only checked by hand. Test it if one is added.
