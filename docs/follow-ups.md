# Follow-ups

Work found during earlier features that wasn't done there. Grouped by when it's due. `/start-feature` reads the section for the current milestone plus "Any feature"; `/finish-feature` adds new items and removes finished ones.

## Any feature
- Activity log (decision 0021): every feature adds its actions to `Action` and calls `record()` from its core functions. A migration that rebuilds `activity_log` must re-create its two triggers.
- Starlette warns that `httpx` for `TestClient` is deprecated in favour of `httpx2`. Look into it; swapping needs the developer's OK.
- `openapi-typescript` has had no release since Feb 2026 and declares TypeScript 5; it runs on TypeScript 6 through an npm `overrides` entry. If it stays unmaintained or breaks on a TypeScript update, consider `@hey-api/openapi-ts` (needs the developer's OK).
- Dev servers: `.claude/launch.json` starts the admin and public apps; add the two Vite dev servers if they're needed.
- `npm audit` reports a moderate minimatch issue inside ESLint's dependencies (dev only). Update ESLint when a fixed release passes the 7-day rule.
- Add branch protection on `main` requiring the "Lint and test", "Frontend checks" and "Scan for secrets" checks (each can be selected once it has run on a PR). Remove this line once it's set up.
- Refactor (planned, protected area: staff auth): move first-run setup's rules (`create_manager()` in `app/admin/api/setup.py`: PIN check, PIN match, gym-name check, save order) into `app/core` (e.g. a `first_run_setup()` returning field errors), so the route stays thin as CLAUDE.md requires. Carried over from the old Jinja route; behaviour must not change (the `test_admin_api_setup.py` tests pin it).

## Milestone 3: phone linking & check-in
- Doctor's notes: the official text says a note must be at most 3 months old. Not enforced (the developer's call, for now); confirm with the manager. A note added by mistake can't be removed (append-only); a "withdrawn" row would be new.
- **Next feature: self sign-up on the phone** (the developer's call, split from feature 4). An unlinked phone at `/c` offers "New here? Sign up" next to linking with a desk code: name, phone and date of birth (the `add_customer()` rules), then the customer, a device session and the `gym_device` cookie are created in one transaction, then the health form, plan page and check-in. A phone number that is already a customer (active or not) is refused with "go to the desk", or anyone could take over a customer. Needs a `customers.self_registered` column (migration) so the milestone 4 dashboard can list new sign-ups; not logged (no staff). Accepted risks: anyone with a photo of the QR can sign up, and the phone number isn't verified. Protected area (customer login and linking): needs a decision record and design doc updates (who adds customers, the linking flow, decision 0029).
- Health form renewal for customers without a phone (an expired form blocks their manual check-in): left for later by the developer. The PC form screen from feature 4 can serve it.
- **The customer at the desk PC uses a logged-in staff session** (code review of feature 4, decision 0033). (1) The form screen hides the staff header, but its cancel link, the browser's Back button and the redirect after signing all lead into the admin app, so a customer left alone can browse other customers. (2) The auto-lock counts only API requests, and filling in the form sends none, so a manager's 5-minute lock can wipe a slow customer's form. One fix for both: a "customer mode" for the form screen that keeps the session alive while it's open and asks for the staff PIN to leave. Protected area (staff auth): the developer decides, before production.

## Milestone 4: admin screens (from Customers)
- Customer list: search, and sorting / filtering by recent check-ins (e.g. who came in the past month), as queries.

## Milestone 4: admin screens
- Role-filtered menus: the Prices page hides its form with `isManager()` from `customers.ts`, a role check in a customer module. Give the screens one helper for this.
- Settings screen: load with `load_gym_settings_for_editing()`, convert form fields to their types before `update_gym_settings()`, and require a manager-only permission on the server. Email addresses are ASCII-only for now (decision 0016).
- Activity log screen (`activity_log.view`) must cope with older before/after shapes.
- Lock screen: style it, add the role-filtered menus in React. A polling dashboard doesn't count as activity, so instructors still lock after 60 idle minutes; the manager can raise `instructor_lock_screen_minutes`.
- Customer page, Phones: the list doesn't refresh itself while a code is on screen, because every React request counts as activity for the auto-lock. Once background refreshes skip the idle timer (the server already allows a request that doesn't `touch`), poll the list and hide the code once a phone links. The device name is a rough guess from the user agent (iPhone / Android / iPad); iPadOS sends a Mac user agent, so iPads show as "other device".
- Dashboard: show the instructor the customers whose form needs a doctor's note, and the forms expiring in the next 30 days (design doc "Validity and access").
- The public build's `src/public/plans.ts` copies the admin build's plan names, `formatShekels()` and `formatMonth()` (`src/admin/prices.ts`), because the two builds never import each other. Give them one shared module (e.g. `src/shared/`) with the styling pass.
- Dashboard: today's check-ins live, from `checkins` (the instructor's answer to fake check-ins, design doc "Fake check-ins").
- The "אין חיבור לשרת" error markup is copied in six screens (setup, lock screen, the three customer pages); make it a shared component.

## Milestone 5: report (from Plan corrections)
- The report reads plan choices with the same rule as `_first_active()` in `app/core/plans.py`: active means no row replaces it, and a "no plan" row (`plan IS NULL`) covers nothing (decision 0026).
- Generate the report outside a request's transaction (a scheduled job or its own short transactions): requests hold the write lock for their whole transaction (decision 0027), so a slow report inside one would hold up every other request.
- Staff choose and correct only choices starting in the current month (decisions 0025, 0026). If the manager needs to fix last month before approving its report, or to stop a tri-monthly period that started earlier, widen that rule once report approval exists.

## Milestones 5–6: report, operations and hosting
- SMTP host/user and the backup folder become settings (after hosting).
- Relative `GYM_DATABASE_PATH` and the `.env` lookup depend on the process's working directory. A missing DB file stops startup, but the two apps could still open different files if started from different folders. Pin a base folder or require absolute paths in prod.
- Packaging: the apps need `alembic.ini` and `migrations/` next to the code at runtime (the startup check reads them), and `npm ci` + `npm run build` must run before they start (a missing build is a 503 page, not a startup error).
- Deployment checks (decision 0030), through the chosen host or tunnel: `X-Forwarded-Proto: https` reaches the public app so the same-origin check passes (otherwise compare against a configured public hostname, `app/core/http.py`); linking and the `Secure` `gym_device` cookie work on a real iPhone and Android phone and survive a reload; `CF-Connecting-IP` (or the host's equivalent) carries the client IP.
- Rate limiting (decision 0029): the app has none and no wrong-code lockout. Before launch, add an edge (Cloudflare) rate-limit rule for `POST /api/link` by IP, and consider one for the whole public hostname. Until then, an unknown number is refused slightly faster than a known one with a wrong code (no code lookup), a timing hint of which numbers are customers'; the edge limit makes it impractical, or always run the lookup.
- Request size: the public app has no body-size limit, and the health form's signature is up to ~400 KB. Add an edge limit for the public hostname (e.g. 1 MB), with the rate limits.
- On real phones: the wall QR opening `/c` in the main browser and checking in at once, and the `gym_device` cookie's year being refreshed by a check-in (decision 0032).
- On real phones: drawing the signature with a finger, the keyboard and toolbar not clearing it, and the PDF it produces.
- Security headers: the design doc asks the public app for HTTPS-only and no-framing headers; add a content security policy for both React builds too.
- Nothing stops an app being started on `0.0.0.0`. Add a guard in the start script / service config.
- Dependabot for the SHA-pinned GitHub Actions.
- Staff sessions (decision 0019): if the admin app moves behind HTTPS on a real hostname, change `ALLOWED_HOSTS` in `app/admin/main.py` and add `Secure` to the `gym_staff` cookie. Prod needs `GYM_SECRET_KEY` (both apps and `alembic`).

## Before launch: confirm with the manager
- Keeping customer data (no deletion on request) is fine (decision 0021).
- The lock times (managers 5 min, instructors 60).
- The instructor/manager permission split, still the design doc's proposal (one-line change in `ROLE_PERMISSIONS` plus its test). That now includes instructors seeing prices and their history (`prices.view`).
- Enter the real prices on the Prices screen; none ship with the system.
- Health form: 12 months from signing (the paper form says "valid for <year>"), the confirmation checkbox's wording, whether the doctor's note must be at most 3 months old, and that names on the form must be in Hebrew or Latin letters (decision 0031).

## Code review leftovers (low priority)
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
- `frontend/` has no test runner, so `shekelsToAgorot()` was only checked by hand. Test it if one is added.
