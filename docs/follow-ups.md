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

## Milestone 5: report (from Plan corrections)
- The report reads plan choices with the same rule as `_first_active()` in `app/core/plans.py`: active means no row replaces it, and a "no plan" row (`plan IS NULL`) covers nothing (decision 0026).
- Generate the report outside a request's transaction (a scheduled job or its own short transactions): requests hold the write lock for their whole transaction (decision 0027), so a slow report inside one would hold up every other request.
- Staff choose and correct only choices starting in the current month (decisions 0025, 0026). If the manager needs to fix last month before approving its report, or to stop a tri-monthly period that started earlier, widen that rule once report approval exists.

## Milestone 5: report (from Punch cards)
- Single-entry billing counts a month's check-ins: leave out the ones charged to a punch card (`checkins.punch_card_id IS NOT NULL`). A card that runs out mid-month followed by single entry must charge only the visits after it (decisions 0042, 0043).
- A card is paid in full in its `bought_month`, with `expires_on` as the end date (the design doc's sample: "1 Mar 2027 (card expiry)"), and 0 in the next month. Read `punch_cards.price_agorot`, never the price table. The screens show the last valid day instead (the day before); check with the developer whether the report should match them.
- A card running out mid-month and then a monthly plan the same month charges both (the card and the month). Confirm with the manager that this is right before the report is approved.

## Punch cards: later
- Cancelling or refunding a card bought by mistake (decision 0043: not built; the phone has a confirm step instead). Design it with the manager: who may cancel, whether used entries stay charged, and how the report shows it. A cancellation is a new row, never an update (the table is append-only).
- The phone's plan page still says "the first check-in this month" when a card ran out mid-month. Reword it if customers find it confusing.
- The card size (20) lives in two places: `CARD_ENTRIES` in `app/core/models/punch_cards.py` and the `checkins_card_entries` trigger. Changing it needs both, in a migration. (The screens get it from the API.)
- Small query savings (code review): `plans._refuse_a_card` re-checks for an active card on the check-in path, where `checkins._what_pays` already knows there's none; the admin plan status runs `active_card()` and `card_history()`, counting the active card twice (it could be picked from the history).

## Milestones 5–6: report, operations and hosting
- Dashboard cards: the report card (manager only, as its own route with the report permission) and the backup card ("last backup", red after 2 days without one), from the design doc's dashboard. The dashboard's lists are one route each, so a card is a new route and a new panel.
- Every request, a dashboard's timed refresh included, takes SQLite's write lock (`BEGIN IMMEDIATE`, decision 0027) although a refresh writes nothing. Milliseconds each today; if many screens poll, give background refreshes a read-only transaction.
- SMTP host/user and the backup folder become settings (after hosting).
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
- The triggers live only in the migrations, not the models (a `create_all` schema would lack them): `activity_log`'s two, `plan_choices`' five (append-only, overlap, same customer, same months) and `checkins`' three (append-only, same customer's phone).
- Test helpers copied across test files belong in `tests/conftest.py`: `log()`, `FAKE_HASH`, `Clock`, `FAKE_PIN_HASH`, `fast_hashing`, `SAME_ORIGIN` (also in `test_admin_api_*.py`, now including the customer and price tests), and the `both_apps` marker (`test_apps.py`, `test_startup.py`).
- Setup validates the gym name twice.
- `MonthText` (the `YYYY-MM` pattern) is in both `app/admin/api/schemas.py` and `app/public/api/schemas.py`, since the public app can't import admin code. Move it to a shared core module (e.g. `app/core/months.py`).
- `test_a_repeat_comes_before_the_plan_check` (`tests/test_checkins.py`) makes its "no plan" row as the customer; only the manager clears plans. Make it through `correct_plan()` with a manager.
- Two migration heads give Alembic's raw error at startup instead of `DatabaseNotReadyError`.
- The naive-datetime checks test `tzinfo is None` rather than `utcoffset() is None`.
- `app/core/spa.py` answers paths whose last segment has a dot with 404, so a future React route with a dot in a parameter would break on reload.
- Lock's network-failure path (always goes to the lock screen) wasn't reproduced by hand.
- The Prices page's Hebrew errors repeat the 24-month and ₪10,000 limits from `app/core/prices.py`; update them together.
- The Plan section's history loads each staff name lazily (`PlanChoice.staff`); `selectinload` would make it one query.
- `age_group_for()` (`app/core/plans.py`), `_years_before()` (`app/core/customers.py`) and `signed_by_guardian()` (`app/core/health_forms.py`) all do birthday date maths; share one helper.
- Customer names entered by staff may use letters Heebo lacks (Cyrillic, Arabic), which print blank in the health form PDF. The form itself refuses such a signer name; decide whether customer names get the same rule.
- `frontend/` has no test runner, so `shekelsToAgorot()` was only checked by hand, and the styling pass was checked only in the browser. Test them if one is added.
- `app/demo_data.py` holds the demo staff PINs in code (public repo). They only open a throwaway dev database, and the script refuses prod and any database with data; generate them instead if that ever matters.
- `ReadOnlyDbSession` (`app/core/db.py`) is used only by `/api/branding`. If more login-free, read-only routes appear, they can use it too; a route that touches a staff or device session writes and can't.
- Settings: the screen sends the whole form, so two managers saving at once overwrite each other (last write wins; both are in the activity log). A version check would need a route contract change.
- Settings: `app/admin/api/settings.py` reads the core's problem keys (`report_recipients.1`) to build its 400. If `gym_settings` returned structured problems (field, position, kind), the route wouldn't depend on that string format.
- The screen-reader-only `.hidden` class is in both `Staff.module.css` and `Settings.module.css`, and each manager-only screen declares its own `Forbidden` (`staff.ts`, `pages/Settings.tsx`). Move them to `ui.module.css` and one shared helper.
- Settings: lock times and report recipients are editable by every manager, not only the owner (developer's call, settings feature). An owner-only permission can be added later if that changes.
