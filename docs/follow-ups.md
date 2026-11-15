# Follow-ups

Work found during earlier features that wasn't done there. Grouped by when it's due. `/start-feature` reads the section for the current milestone plus "Any feature"; `/finish-feature` adds new items and removes finished ones.

## Any feature
- Activity log (decision 0021): every feature adds its actions to `Action` and calls `record()` from its core functions, and gives each new action (and any new before/after field) a Hebrew name in `frontend/src/admin/activityLog.ts`; a missing one shows its stored name. A migration that rebuilds `activity_log` must re-create its two triggers.
- A new manager-only admin route goes in `MANAGER_ONLY` (`tests/test_admin_manager_only_routes.py`); the test fails until it does. React offers actions with `can(session, "<permission>")` (`roles.ts`), never by role.
- Starlette warns that `httpx` for `TestClient` is deprecated in favour of `httpx2`. Look into it; swapping needs the developer's OK.
- `openapi-typescript` has had no release since Feb 2026 and declares TypeScript 5; it runs on TypeScript 6 through an npm `overrides` entry. If it stays unmaintained or breaks on a TypeScript update, consider `@hey-api/openapi-ts` (needs the developer's OK).
- Dev servers: `.claude/launch.json` starts the admin and public apps; add the two Vite dev servers if they're needed.
- `npm audit` reports a moderate minimatch issue inside ESLint's dependencies (dev only). Update ESLint when a fixed release passes the 7-day rule.
- Add branch protection on `main` requiring the "Lint and test", "Frontend checks" and "Scan for secrets" checks (each can be selected once it has run on a PR). Remove this line once it's set up.
- Refactor (planned, protected area: staff auth): move first-run setup's rules (`create_manager()` in `app/admin/api/setup.py`: PIN check, PIN match, gym-name check, save order) into `app/core` (e.g. a `first_run_setup()` returning field errors), so the route stays thin as CLAUDE.md requires. Carried over from the old Jinja route; behaviour must not change (the `test_admin_api_setup.py` tests pin it).

## Milestone 3: phone linking & check-in
- Doctor's notes: the official text says a note must be at most 3 months old. Not enforced (the developer's call, for now); confirm with the manager. A note added by mistake can't be removed (append-only); a "withdrawn" row would be new.
- Health form renewal for customers without a phone (an expired form blocks their manual check-in): left for later by the developer. The PC form screen from feature 4 can serve it.

## Milestone 4: admin screens
- Activity log: the target filter is exact, so a customer's plan choices, check-ins and forms (other target types) don't show under that customer. A full customer history would need a `customer_id` column or a JSON search.
- Lock screen: the dashboard's timed refreshes don't count as activity, so instructors still lock after 60 idle minutes; the manager can raise `instructor_lock_screen_minutes`.
- Customer page, Phones: the device name is a rough guess from the user agent (iPhone / Android / iPad); iPadOS sends a Mac user agent, so iPads show as "other device". The list refreshes itself only while a link code shows (the Refresh button is gone), so a phone change made elsewhere shows on the next page load.
- Staff header: on a window narrower than about 480px the menu is wider than the page and pushes it sideways (every staff screen). The desk PC is wide; fix if the admin app is ever used on a small screen.
- Customer list search: names in other alphabets (Cyrillic, accented Latin) match only in the case typed, since SQLite's `LIKE` folds English letters only. If staff need it, a lowercased search column (schema change) fixes it. Name search reads the whole `customers` table (`LIKE '%…%'`); fine at hundreds of customers, FTS5 if it ever gets slow.
- Customer list: the search text sits in the desk PC's address bar and browser history (the server log drops it). Acceptable on a staff-only PC; revisit if the admin app is ever used elsewhere.
- Styling pass leftovers (decision 0034): the health form's yes/no answers hide their radio buttons visually (the labels are the controls), so check them with a real screen reader (NVDA on the desk PC, VoiceOver on a phone).

## Report: later
- Staff choose and correct only choices starting in the current month (decisions 0025, 0026). If the manager needs to fix last month before approving its report, or to stop a tri-monthly period that started earlier, that rule must widen (protected plan logic, its own fix). Not done in report delivery.
- A failed generation shows on the Reports screen only as "failed" (with a hint to close the file in Excel); the cause is in the server log. A claim on a month (generation or sending) expires after 10 minutes (`CLAIM_LIFETIME`) in case its job never ran.
- Approve and send has no confirmation step (decision 0045): one click emails the report to the recipients, which can't be undone. Ask the manager whether an "are you sure? (N recipients)" step is wanted.
- The scheduled job checks last month only (decision 0045): a PC off for more than a whole month never generates the month before on its own (the manager can, from the Reports screen). The first 1st after install emails a report even if it's empty.
- Report emails: a timeout after the mail server already accepted an email makes the retry send it twice (accepted). Only STARTTLS is supported (Gmail on 587); a server with implicit TLS only (465) needs `SMTP_SSL`.
- The Reports screen has two primary buttons side by side once a report exists (Approve and send, Regenerate); Regenerate kept its look (not in report delivery's scope). Make it a quiet button if the manager finds it confusing.
- Filter the report's rows, starting with leaving out customers who pay 0 that month (months 2–3 of a tri-monthly plan, a punch card carried over with entries left). Its own session, after report delivery (the developer's call). Options discussed: (A) a "hide rows with 0" checkbox on the Reports preview only, files and emails unchanged; (B) a manager setting copied onto each generation (a new `reports` column, e.g. `hide_zero_rows`), so the files, the emails and the preview leave those rows out while the calculation and the snapshot keep every row, and regenerating a past month uses that month's own saved choice (past reports regenerate identically); (C) a checkbox beside Generate / Regenerate saved on the generation, still needing B's setting as the scheduled job's default. B was the recommendation if the recipients shouldn't see 0 rows. Ask first who reads the report (an accountant collecting payments, or someone checking who's covered) and whether other filters (e.g. by plan type) are wanted. Touches report logic and the schema (protected areas).

## Punch cards: later
- Cancelling or refunding a card bought by mistake (decision 0043: not built; the phone has a confirm step instead). Design it with the manager: who may cancel, whether used entries stay charged, and how the report shows it. A cancellation is a new row, never an update (the table is append-only).
- The phone's plan page still says "the first check-in this month" when a card ran out mid-month. Reword it if customers find it confusing.
- The card size (20) lives in two places: `CARD_ENTRIES` in `app/core/models/punch_cards.py` and the `checkins_card_entries` trigger. Changing it needs both, in a migration. (The screens get it from the API.)
- Small query savings (code review): `plans._refuse_a_card` re-checks for an active card on the check-in path, where `checkins._what_pays` already knows there's none; the admin plan status runs `active_card()` and `card_history()`, counting the active card twice (it could be picked from the history).

## Milestones 5–6: report, operations and hosting
- Dashboard: the backup card ("last backup", red after 2 days without one), from the design doc's dashboard: a new route and a new panel, like the report card (`GET /api/reports/latest`). Backups can add their own "is it due?" check to the report job's hourly loop (`app/core/report_schedule.py`, decision 0045) rather than a second thread.
- Every request, a dashboard's timed refresh included, takes SQLite's write lock (`BEGIN IMMEDIATE`, decision 0027) although a refresh writes nothing. Milliseconds each today; if many screens poll, give background refreshes a read-only transaction.
- SMTP host/user and the backup folder become settings (after hosting). The SMTP password (`GYM_SMTP_PASSWORD`, a Gmail app password) moves to the production secret store with the other secrets.
- Report email on the real deployment (decision 0030): send through the gym's Google account with an app password, and check the Hebrew subject, body and attachment names in Gmail and Outlook, and that a failed send shows red on the dashboard and goes out on the next hourly run. Prod refuses to start without `GYM_SMTP_*`; `outbox/` is dev only.
- The reports folder (`GYM_REPORTS_DIR`, default `reports/` relative to the working directory) holds names and amounts: include it in backups, and pin it to an absolute path in prod with the database path.
- Relative `GYM_DATABASE_PATH` and the `.env` lookup depend on the process's working directory. A missing DB file stops startup, but the two apps could still open different files if started from different folders. Pin a base folder or require absolute paths in prod.
- Packaging: the apps need `alembic.ini` and `migrations/` next to the code at runtime (the startup check reads them), and `npm ci` + `npm run build` must run before they start (a missing build is a 503 page, not a startup error).
- Deployment checks (decision 0030), through the chosen host or tunnel: `X-Forwarded-Proto: https` reaches the public app so the same-origin check passes (otherwise compare against a configured public hostname, `app/core/http.py`); linking and the `Secure` `gym_device` cookie work on a real iPhone and Android phone and survive a reload; `CF-Connecting-IP` (or the host's equivalent) carries the client IP.
- Rate limiting (decision 0029): the app has none and no wrong-code lockout. Before launch, add an edge (Cloudflare) rate-limit rule for `POST /api/link` and `POST /api/sign-up` (decision 0035) by IP, and consider one for the whole public hostname. Until then, an unknown number is refused slightly faster than a known one with a wrong code (no code lookup), a timing hint of which numbers are customers'; the edge limit makes it impractical, or always run the lookup.
- Request size: the public app has no body-size limit, and the health form's signature is up to ~400 KB. Add an edge limit for the public hostname (e.g. 1 MB), with the rate limits.
- On real phones: the wall QR opening `/c` in the main browser and checking in at once, and the `gym_device` cookie's year being refreshed by a check-in (decision 0032).
- On real phones (self sign-up, decision 0035): the sign-up form's autofill (name, phone, birthday) and the date picker for the date of birth.
- On real phones: drawing the signature with a finger, the keyboard and toolbar not clearing it, and the PDF it produces.
- Security headers: the design doc asks the public app for HTTPS-only and no-framing headers; add a content security policy for both React builds too. The logo (`/branding/logo`) and the bundled Heebo font are same-origin, so `img-src`/`font-src 'self'` covers them.
- On real phones (styling pass): the check-in result's entrance animation and kettlebell shape, the repeat result's `color-mix()` colour (with its plain fallback on Safari before 16.2), and the 16px inputs not zooming on iOS.
- Page weight: both builds bundle the whole Heebo TTF (122 KB). If the phone's first load is slow on mobile data, ship a Hebrew + Latin WOFF2 subset instead.
- Nothing stops an app being started on `0.0.0.0`. Add a guard in the start script / service config.
- Dependabot for the SHA-pinned GitHub Actions.
- Database key (decision 0048), for server setup: pick an OS with glibc 2.28 or newer (the `sqlcipher3` wheels), generate `GYM_DATABASE_KEY` there, and print it with the other keys to keep off the machine before any real data goes in. If a plain database is moved over, run `python -m app.encrypt_database` (both apps stopped, after a backup) and delete the `gym.db.plain-<date>` it leaves once the apps start. Watch `sqlcipher3` releases: they carry its bundled OpenSSL's security fixes.
- Backups (feature 2) copy the encrypted database: a copy taken through a keyed connection (SQLite's backup API) stays encrypted with the same key, so restoring one needs both the backup password and `GYM_DATABASE_KEY`. Test a restore with both.
- The database key can't be changed yet (`PRAGMA rekey`), and there's no decrypt command. Add one if the key ever leaks.
- Owner account (decision 0039): nobody else can reset the owner's PIN, so a forgotten one needs a command run on the PC itself (e.g. `python -m app.reset_owner_pin`, with both apps stopped, logged as the owner). No ownership transfer either (the gym changing hands); add one if it's ever needed.
- Staff sessions (decision 0019): if the admin app moves behind HTTPS on a real hostname, change `ALLOWED_HOSTS` in `app/admin/main.py` and add `Secure` to the `gym_staff` cookie. Prod needs `GYM_SECRET_KEY` (both apps and `alembic`).

## Before launch: confirm with the manager
- Staff stay with a customer filling in the health form on the desk PC: the form runs in a logged-in staff session, so a customer left alone could leave it for the admin app, and a manager's 5-minute lock can wipe a slow customer's form (no customer mode, decision 0037). A customer tablet with its own screen may come later.
- Keeping customer data (no deletion on request) is fine (decision 0021).
- The lock times (managers 5 min, instructors 60).
- The instructor/manager permission split, still the design doc's proposal (one-line change in `ROLE_PERMISSIONS` plus its test). That now includes instructors seeing prices and their history (`prices.view`).
- Enter the real prices on the Prices screen; none ship with the system.
- Insurance with a "yes" on the health form (decision 0041): a customer whose form has a "yes" now trains before the manager reviews it. Confirm with the insurer that a signed form with a "yes" covers them, or go back to blocking until a doctor's note.
- Health form: 12 months from signing (the paper form says "valid for <year>"), the confirmation checkbox's wording, whether the doctor's note must be at most 3 months old, and that names on the form must be in Hebrew or Latin letters (decision 0031).

## Code review leftovers (low priority)
- Forms waiting for review (decision 0041): the public API's health form state still lists `needs_doctor_note`, which the phone can no longer receive; `FormState.NEEDS_DOCTOR_NOTE`, `forms_needing_doctor_note()` and `/api/health-forms/needing-note` now mean "waiting for the manager's review" (a note or an acceptance). Rename them (API contract changes) before more screens use them. `AcceptForm` and `DoctorNoteUpload` on the customer page repeat the same answer handling; share it if a third review action comes.
- The triggers live only in the migrations, not the models (a `create_all` schema would lack them): `activity_log`'s two, `plan_choices`' five (append-only, overlap, same customer, same months), `checkins`' five (append-only, same customer's phone and card, a card's 20 entries), `punch_cards`' two and `reports`' two (append-only).
- Test helpers copied across test files belong in `tests/conftest.py`: `log()`, `FAKE_HASH`, `Clock`, `FAKE_PIN_HASH`, `fast_hashing`, `SAME_ORIGIN` (also in `test_admin_api_*.py`, now including the customer and price tests), and the `both_apps` marker (`test_apps.py`, `test_startup.py`).
- Setup validates the gym name twice.
- The Hebrew plan names are in two places: `PLAN_NAMES` in `frontend/src/shared/plans.ts` (screens) and in `app/core/report_files.py` (the report's files, made on the server). Each points to the other; change both together.
- `MonthText` (the `YYYY-MM` pattern) is in both `app/admin/api/schemas.py` and `app/public/api/schemas.py`, since the public app can't import admin code. Move it to a shared core module (e.g. `app/core/months.py`).
- `test_a_repeat_comes_before_the_plan_check` (`tests/test_checkins.py`) makes its "no plan" row as the customer; only the manager clears plans. Make it through `correct_plan()` with a manager.
- Two migration heads give Alembic's raw error at startup instead of `DatabaseNotReadyError`.
- The naive-datetime checks test `tzinfo is None` rather than `utcoffset() is None`.
- `app/core/spa.py` answers paths whose last segment has a dot with 404, so a future React route with a dot in a parameter would break on reload.
- Lock's network-failure path (always goes to the lock screen) wasn't reproduced by hand.
- The Prices page's Hebrew errors repeat the 24-month and ₪10,000 limits from `app/core/prices.py`; update them together.
- The Plan section's history loads each staff name lazily (`PlanChoice.staff`); `selectinload` would make it one query.
- `age_group_for()` (`app/core/plans.py`), `_years_before()` (`app/core/customers.py`) and `signed_by_guardian()` (`app/core/health_forms.py`) all do birthday date maths; share one helper.
- Report delivery (code review): the month claim (`_claims`, `_is_claimed`, release by token) is copied in `report_generation` and `report_delivery`; share one small helper. The "newest generation of a month" query is written three times (`report_generation.latest`, `report_delivery.status`, `_newest_report_id`), and `GET /api/reports/{month}` runs it twice. `report_delivery.status()` loads each step's staff lazily (`selectinload` would make it one query; the dashboard polls it every minute). A generation's claim is still held for 10 minutes if its request fails after claiming; delivery now releases its claim on rollback (`_release_unless_committed`), generation could do the same.
- Test fakes for report email (`Outbox`, `FakeSend`), the claim-clearing fixtures and `fresh()` are repeated across `test_report_delivery.py`, `test_report_schedule.py` and `test_admin_api_reports.py`, and `test_report_schedule.py` imports helpers from `test_report_delivery.py`. Move them to `tests/conftest.py`.
- Customer names entered by staff may use letters Heebo lacks (Cyrillic, Arabic), which print blank in the health form PDF. The form itself refuses such a signer name; decide whether customer names get the same rule.
- `frontend/` has no test runner, so `shekelsToAgorot()` was only checked by hand, and the styling pass was checked only in the browser. Test them if one is added.
- `app/demo_data.py` holds the demo staff PINs in code (public repo). They only open a throwaway dev database, and the script refuses prod and any database with data; generate them instead if that ever matters.
- `ReadOnlyDbSession` (`app/core/db.py`) is used only by `/api/branding`. If more login-free, read-only routes appear, they can use it too; a route that touches a staff or device session writes and can't.
- Settings: the screen sends the whole form, so two managers saving at once overwrite each other (last write wins; both are in the activity log). A version check would need a route contract change.
- Settings: `app/admin/api/settings.py` reads the core's problem keys (`report_recipients.1`) to build its 400. If `gym_settings` returned structured problems (field, position, kind), the route wouldn't depend on that string format.
- The screen-reader-only `.hidden` class is in both `Staff.module.css` and `Settings.module.css`, and each manager-only screen declares its own `Forbidden` (`staff.ts`, `pages/Settings.tsx`). Move them to `ui.module.css` and one shared helper.
- Settings: lock times and report recipients are editable by every manager, not only the owner (developer's call, settings feature). An owner-only permission can be added later if that changes.
