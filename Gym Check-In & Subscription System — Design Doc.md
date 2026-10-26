# Gym Check-In & Subscription System — Design Doc

Oct 7, 2026 · @Liran · Updated Oct 14, 2026 (health form, punch cards, hosting under review)

## Overview

A check-in and subscription system that runs on the gym's front-desk PC: customers scan one QR code on the wall with their own phone, the visit is logged, and a month-end report goes to the billing section.

The phone opens the gym's check-in page, which is served from the gym PC through a secure tunnel. The page recognises the phone from a login cookie saved the first time, logs the visit, and shows the customer their status. Staff (the manager and instructors) manage customers on the gym PC itself, each with their own login and permissions.

**Decisions made**

- Check-in: customers scan a fixed wall QR with their own phone (no personal QR codes, no desk scanner).
- Hosting: the system runs on the gym PC; Cloudflare Tunnel makes the customer check-in page reachable from phones. No cloud server. **Under review:** the manager wants the system always on, so it will probably move to a server (the village's server or a paid VPS). See Open questions.
- Plans: customers choose their own plan (monthly, tri-monthly or single entry) on their phone at their first check-in of each month, which also confirms they're continuing. Punch cards are coming as a fourth option (see Punch cards).
- Health form: every customer must have a valid signed health form before any check-in. It's filled in on the phone, or uploaded as a paper form by staff (see Health form).
- Prices: the manager keeps an editable price table with adult and under-18 prices for every plan.
- Report: generated automatically on the 1st, emailed to the manager, and sent on to the other recipients once the manager approves it.

**Goals**

- Record every arrival (date and time) with one scan, in a few seconds.
- Keep customers logged in on their phone, so after the first visit a check-in is just a scan.
- Let customers pick and confirm their plan themselves each month, so the instructor doesn't have to.
- Let instructors handle desk work (new customers, linking phones, manual check-ins) while plan corrections, freezes, prices, reports and settings stay with the manager.
- Make sure no one trains without a valid health form, because the gym isn't insured otherwise.
- Produce and deliver the month-end report without anyone having to remember it.
- Keep data safe with automatic, encrypted, off-site backups.

**Non-goals**

- No payment processing or payment tracking. The report is send-and-go; billing is handled by a separate section.
- No app install. Customers use their phone's browser.
- No access while the gym PC is off. Customers see their status when they check in; the site is offline when the gym is closed.
- No admin access from outside the gym. Admin screens are only reachable on the gym PC itself.

## Users and roles

There are three roles. Staff (the manager and instructors) each have their own login on the gym PC, and what they can do depends on their role. Customers have no username or password and are identified by a login cookie on their phone.

| Role | How they use it | Can do |
| --- | --- | --- |
| Manager | Admin app on the gym PC, own login | Everything, including prices, reports, settings and staff accounts |
| Instructor | Admin app on the gym PC, own login | Day-to-day desk work: check-ins, new customers, linking phones (see table below) |
| Customer | Own phone browser, via the wall QR | See their own status; choose their own plan once a month |

**Permissions** (*proposed*; the manager confirms the final split)

| Action | Instructor | Manager |
| --- | --- | --- |
| See the dashboard, today's check-ins, customer list and customer pages | Yes | Yes |
| Manual check-in (with no plan this month, an instructor's check-in records single entry) | Yes | Yes |
| Pick a plan for a customer who has none this month | No | Yes |
| Add a customer; edit name, phone and notes | Yes | Yes |
| Link or unlink a customer's phone | Yes | Yes |
| See whether a customer's health form is valid and when it expires | Yes | Yes |
| Upload a signed paper health form for a customer | Yes | Yes |
| View the contents of a health form | No | Yes |
| Edit a customer's date of birth (sets the under-18 price) | No | Yes |
| Change or clear a plan already chosen | No | Yes |
| Freeze a plan | No | Yes |
| Archive or delete a customer | No | Yes |
| Edit prices | No | Yes |
| View, regenerate, approve and send reports | No | Yes |
| Settings, backups and restore | No | Yes |
| Manage staff accounts and reset their PINs | No | Yes |
| View the activity log | No | Yes |

Permissions are defined in code as named permissions (e.g. `prices.edit`, `plans.correct`) mapped to roles in one place, so moving an action from one role to the other is a one-line change. Every action is checked on the server; hiding a button in the interface is never the only protection.

**Staff login and lock screen.** The admin app opens on a lock screen: tap your name, enter your PIN (at least 6 digits). The app locks again when someone presses "Lock", and on its own after a stretch without activity: 5 minutes for a manager, 60 for an instructor (instructors mostly watch the desk screen and check people in). Both times are settings the manager can change. Any session ends after 12 hours. Staff should still lock or log in as themselves, since the activity log records whoever is logged in. The header always shows who is logged in and their role. Menus and buttons a role can't use are hidden.

**Activity log.** Every change made by staff (who, what, when, before and after) is recorded, so the manager can see what instructors did.

**First run.** The app asks for the first manager account; the manager then creates instructor accounts. There can be more than one manager.

**Windows account.** The PC itself has a Windows password and locks after 10 minutes idle. This is separate from the staff logins in the app.

## Architecture

One codebase runs as two local web apps on the gym PC: an admin app reachable only on the PC, and a public app with just the customer pages, exposed to phones through Cloudflare Tunnel.

&#91;embedded content: system architecture · one PC, two apps, one tunnel\]

The tunnel is an outbound connection from the PC, so no router ports are opened. Phones only ever reach the public app; admin routes do not exist on that port.

| Part | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.12 + FastAPI | Simple, well supported, easy for Claude Code to build and test |
| Database | SQLite (single file, WAL mode) | No database server; two local apps can share it safely |
| Apps | Same codebase, two instances: admin on `127.0.0.1:8000`, public on `127.0.0.1:8001` | Admin routes are never mounted on the public instance |
| Frontend | Server-rendered HTML + a little JavaScript; customer pages mobile-first | No build step; works in any phone browser |
| Tunnel | Cloudflare Tunnel (`cloudflared` as a Windows service), free plan | HTTPS handled by Cloudflare; no open ports; no static IP needed |
| Domain | A gym domain on Cloudflare, e.g. `checkin.<gym-domain>` | Needed for a named tunnel and a stable QR URL; about $10–15/year |
| Scheduled jobs | Run inside the admin app at startup and every hour (APScheduler or a simple loop) | Monthly report on or after the 1st, daily backup; catches up if the PC was off |
| Email | SMTP through the gym's Google account with an app password | Sends the report to the manager and, after approval, to the recipients |
| Admin window | Edge or Chrome in app mode (`--app=http://127.0.0.1:8000`) | Looks like a desktop app, no address bar |
| Startup | Both apps and `cloudflared` as Windows services (e.g. via NSSM), admin window at log-on | Everything is up as soon as the PC starts |
| Reports | openpyxl (Excel) + a PDF library | Standard, offline |

**Availability**: phone check-ins work only while the PC is on and the gym has internet. If either is down, the instructor checks people in manually on the PC.

**Webcam (optional)**: browsers allow camera access on `127.0.0.1`, so the admin can take a customer photo from the registration screen without extra software.

## Check-in flow

A linked phone checks in with one scan of the wall QR; a new phone is linked once with a short code from the desk, and the first check-in of each month also asks the customer to choose a plan.

&#91;embedded content: check-in flow · link once, choose a plan once a month\]

Every check-in runs the same checks in order: **linked phone → valid health form → plan for this month → checked in**. If the customer has no valid health form (never filled in, or expired), the phone shows the health form before anything else (see Health form).

The plan page lists the three plans with this customer's prices (adult or under 18); see Plans, prices and billing. A missing plan never blocks entry: a customer who backs out of the plan page can still talk to the instructor, who can check them in manually. **A missing health form always blocks entry**, by phone and manually.

**The wall QR**

- Encodes one fixed URL, e.g. `https://checkin.<gym-domain>/c`, printed and mounted at the entrance.
- Anyone can open it, but only a linked phone gets checked in.
- Customers should scan with the phone's built-in Camera app, which opens the link in the main browser. Third-party scanner apps often use an in-app browser with separate storage, so the phone would look unlinked.

**Linking a phone (first visit, new phone, lost login)**

1. On the customer's page, a staff member (instructor or manager) clicks "Link a phone". The admin app shows a 6-digit code, valid for 10 minutes and usable once.
2. The customer scans the wall QR. The phone isn't recognised, so the link page opens; they enter their phone number and the code.
3. The server checks both, creates a device session, sets the login cookie, and checks the customer in straight away.

A customer can have up to 3 linked phones. The customer page lists them (device, last used) with an "Unlink" button for each.

**Login cookie**

- Name `gym_device`, set by the server in the HTTP response: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, `Max-Age` of 1 year, refreshed on every check-in.
- Value: a random 32-byte token. Only its SHA-256 hash is stored in the database.
- Never store the login in `localStorage`, `sessionStorage` or IndexedDB: Safari deletes script-written storage after 7 days without a visit. Server-set first-party cookies are not subject to that rule ([WebKit](https://bugs.webkit.org/show_bug.cgi?id=237350), [WebKit blog](https://webkit.org/?p=10218)).
- Customers do not need to change any Safari settings.

**Fake check-ins**

A photo of the wall QR opens the page from anywhere, so a linked phone could check in from home. This is an accepted risk: the instructor sees every check-in live on the dashboard, and there's no benefit to the customer. If it becomes a problem, a later version can show a rotating code on the desk screen instead of a printed QR.

**Manual check-in**

From the customer list, a staff member finds the customer and clicks "Check in". It records who did it, is logged with method `manual`, and works even when the internet is down. If the customer has no valid health form, the button is disabled and the dialog offers "Upload paper form" instead; once a signed paper form is uploaded, the check-in goes ahead.

## Plans, prices and billing

Customers choose their own plan on their phone at their first check-in of each month; the system works out what each customer owes from those choices and the manager's price table. Rules marked *assumption* need the manager's confirmation (see Open questions).

| Plan | Covers | Payment in the report | Subscription end in the report |
| --- | --- | --- | --- |
| Monthly | The calendar month it's chosen in | Monthly price | Last day of that month |
| Tri-monthly | The month it's chosen in and the next two | Full tri-monthly price in the first month, ₪0 in the other two | Last day of the third month |
| Single entry | Each visit in the month it's chosen in | Number of visits × single-entry price | Empty |

**The monthly choice**

- At a customer's first check-in in a calendar month, if no plan covers that month, the phone shows the plan page: the three plans with this customer's prices. Tapping one confirms it and completes the check-in. The choice doubles as the customer's confirmation to keep training that month.
- Inside a tri-monthly period there's nothing to choose; the status page says "Covered by your 3-month plan until 31 Dec".
- Once chosen, the plan is fixed for that month on the phone. Corrections are manager-only, and the row records who made them.
- Instructors never choose or change plans. If an instructor checks in someone who has no plan for the month, the check-in records single entry for that month (chosen by staff, with the instructor recorded), so the visit is counted and the month is never left without a plan. A customer who wants a different plan asks the manager, who corrects it (a new row; the single-entry row is kept). Because the month now has a plan, the phone doesn't show the plan page for it.
- If the manager checks in someone who has no plan for the month, the check-in dialog asks them to pick one.
- With single entry chosen, every visit that month counts as one paid entry.
- A customer who doesn't check in during a month chooses nothing and doesn't appear in that month's report (*assumption*).

**Prices**

- The manager keeps one price table: each plan has an adult price and an under-18 price. Only the manager can edit it, on the Prices screen.
- Each price change has a "valid from" month. New prices apply from that month on; earlier months keep their old prices, so past reports never change.
- The price is copied onto the customer's choice when it's made, so later price changes don't affect it.
- Under 18 is worked out from the customer's date of birth on the 1st of the month (*assumption*): someone who turns 18 mid-month pays the under-18 price until the next month.
- The actual amounts aren't known yet; the system ships with placeholder prices that the manager replaces before launch.

**Freezes**

A monthly customer who doesn't come in simply isn't charged, so freezes only matter for tri-monthly plans. The manager enters a freeze in whole months; it pushes the end of the tri-monthly period back by the same number of months (*assumption*), and frozen months show ₪0.

**History**

Choices are never overwritten. Each one is a row with plan, months covered, price and who made it, which keeps every past report reproducible.

**Punch cards** (*upcoming; details pending from the manager*)

A punch card is a fixed number of entries (e.g. 12) bought for one price; each check-in uses one entry, and the customer pays again only when they buy a new card. The planned approach, to be confirmed:

- Its own table (`punch_cards`), not `plan_choices`, because a card isn't tied to calendar months.
- The remaining balance is never stored. It's calculated as entries minus the check-ins charged to the card (`checkins.punch_card_id`), so history stays intact and reports stay reproducible.
- A monthly or tri-monthly plan covering the month takes priority; otherwise a check-in uses an active card; otherwise the plan page appears.
- The report shows the card's price in the month it was bought.

Nothing is built for this yet; the rest of the design must simply not rule it out.

## Health form

Every customer needs a valid signed health declaration before they can train. Without one the gym isn't insured, so this is the one thing that blocks a check-in.

**On the phone**

- After linking, and whenever the form is missing or expired, the phone shows the health form before the plan page: the declaration questions, a confirmation checkbox, the customer's full name and a finger-drawn signature.
- Customers under 18 (from their date of birth) get the version signed by a parent or guardian (*assumption*).
- On submit, the system stores the answers, the form version, and a PDF snapshot of exactly what was signed, so the form stays readable even after the questions change.

**On paper (at the desk)**

- For customers without a smartphone, or with an existing paper form, staff upload a photo or scan from the customer page and enter the date it was signed.
- This is also how manual check-in handles a customer with no valid form.

**Validity and access**

- A form is valid for 12 months from the date it was signed (*assumption*). The dashboard lists forms expiring in the next 30 days, and the next scan after expiry asks for a new form.
- Instructors see only "valid until …" or "missing / expired". Only the manager can open a form's contents, and every opening is written to the activity log.
- Old forms are kept (never overwritten); the newest valid one counts.
- The exact questions follow the official health declaration form the manager provides.

## Data model

One SQLite file (`gym.db`, WAL mode) with twelve tables (thirteen once punch cards are added). All timestamps are stored in UTC and shown in Israel local time, so daylight-saving switches never shift a check-in. Money is stored in whole agorot (integers), never as floats.

| Table | Key columns | Notes |
| --- | --- | --- |
| `customers` | id, first\_name, last\_name, phone (unique, normalised), date\_of\_birth, notes, photo (nullable blob), created\_at, archived\_at | Date of birth sets the under-18 price; archive instead of delete |
| `device_sessions` | id, customer\_id, token\_hash (unique), user\_agent, created\_at, last\_seen\_at, revoked\_at | One row per linked phone; at most 3 active per customer |
| `link_codes` | id, customer\_id, code\_hash, expires\_at, used\_at, failed\_attempts | 6-digit code, 10-minute expiry, single use |
| `plan_choices` | id, customer\_id, plan (monthly / tri\_monthly / single\_entry), start\_month, end\_month, age\_group, unit\_price\_agorot, chosen\_at, chosen\_by (customer / admin), replaced\_by | Tri-monthly spans 3 months; corrections add a new row and point the old one at it |
| `prices` | id, plan, age\_group (adult / under\_18), amount\_agorot, valid\_from\_month | The manager's price table; the newest row valid for a month wins |
| `freezes` | id, customer\_id, start\_month, end\_month, reason | Whole calendar months; extends a tri-monthly period |
| `checkins` | id, customer\_id, checked\_in\_at, method (phone / manual), device\_session\_id (nullable), entered\_by | Single-entry payments count these |
| `reports` | id, month, xlsx\_path, pdf\_path, generated\_at, emailed\_to\_manager\_at, approved\_at, sent\_to\_recipients\_at | One row per month; tracks the send-and-approve steps |
| `settings` | key, value | Gym name, manager email, recipient emails, SMTP settings, backup folder, lock-screen minutes (manager and instructor) |
| staff\_users | id, display\_name, role (manager / instructor), pin\_hash, failed\_attempts, last\_failed\_at, locked\_until, active, created\_at | One row per staff member; deactivate instead of delete |
| activity\_log | id, staff\_user\_id, action, target\_type, target\_id, before\_json, after\_json, at | Written for every staff change; read-only in the app |
| `health_forms` | id, customer\_id, source (phone / paper), form\_version, answers\_json (nullable for paper), signer\_name, signed\_by\_guardian, signed\_on, expires\_on, document (blob: PDF snapshot or uploaded scan), uploaded\_by (nullable), created\_at | Never overwritten; the newest valid row counts. The document is stored inside the database, not as a loose file, so it gets the same encryption and backups |

**Rules the code and database enforce**

- At most one active plan choice covers any customer-month.
- Login tokens and link codes are stored only as hashes; the plain values exist only in the cookie or on the admin screen.
- Linking a phone fails after 5 wrong codes for the same phone number, locking that number for 15 minutes. The public app also rate-limits by IP.
- No check-in (phone or manual) is recorded for a customer without a valid health form on that day.
- A second check-in by the same customer within 10 minutes is ignored (shown as "already checked in") and doesn't count as an extra single entry.
- Staff PINs (6–12 digits) are stored as Argon2id hashes, and 5 wrong PINs in a row (each within 15 minutes of the last) lock that account for 5 minutes; the SMTP password is kept in the OS secret store or an environment variable (TBD), not in the database.

## Monthly report

On the 1st of each month the system builds the previous month's report and emails it to the manager; the manager checks it and, if it's right, approves it, which sends it on to the other recipients.

**Steps**

1. **Generate**: on the 1st, the app builds the report for the previous month. If the PC is off on the 1st, it does this at the first startup on or after the 1st. It never generates the same month twice on its own.
2. **Email the manager**: the report goes to the manager's address with the Excel and PDF attached.
3. **Review**: the manager opens the report on the admin Reports screen. If something is wrong, the manager fixes the data (a plan choice, a check-in) and clicks "Regenerate".
4. **Approve and send**: the manager clicks "Approve and send", and the app emails the report to the recipient list in Settings. Forwarding the email by hand also works.

The dashboard shows where the current month's report stands (generated, emailed, approved, sent) and flags a failed email so it can be retried.

**Columns** (one row per customer who had a plan that month)

| First name | Last name | Payment (₪) | Subscription ends |
| --- | --- | --- | --- |
| Dana | Levi | Monthly price | 31 Oct 2026 |
| Lior | Ben-David | Tri-monthly price (first month of the period) | 31 Dec 2026 |
| Noa | Friedman | 0 (covered by a tri-monthly plan) | 30 Nov 2026 |
| Yossi | Cohen | 3 × single-entry price | (empty) |

Payment uses the price saved on each customer's choice, including the under-18 price where it applies. The last row shows the total to be collected.

**Format and storage**

- Excel (.xlsx) and PDF, saved to a `reports/` folder (included in backups) and named `report-2026-10.xlsx`.
- Regenerating a past month gives the same result, because it's calculated from history, not from current state.
- Email goes out through SMTP from the gym's Google account, using an app password. It needs internet; if sending fails, the app retries at the next startup.

## Security and backups

The only thing reachable from outside is the public app's check-in pages; everything else stays on the PC, protected by disk encryption and passwords, with encrypted backups off-site.

**Public app (reachable through the tunnel)**

- Mounts only the customer routes: the check-in page, the link page, and static files. Admin routes are not registered on this instance, so they can't be reached even by guessing URLs.
- Listens on `127.0.0.1:8001` only; `cloudflared` is the one thing that connects to it. No router ports are opened.
- Shows a customer only their own name, plan and visit count, never other customers' data.
- Rate-limits requests by IP, and locks linking for a phone number after 5 wrong codes (see Data model).
- Sends security headers (HTTPS-only, no framing) and rejects requests that don't come through the tunnel's hostname.
- Dependencies (Python packages, `cloudflared`) are kept up to date; Windows Update stays on.

**On the PC**

- **BitLocker** (or Device encryption on Windows Home) encrypts the whole disk, protecting the data if the PC or its drive is stolen.
- **Windows password** with auto-lock after 10 minutes idle.
- **Staff logins with roles**: every action is checked against the logged-in staff member's role, and the app locks after a few idle minutes, longer for instructors (see Users and roles).
- **Admin app** listens on `127.0.0.1:8000` only, so nothing on the gym WiFi or the internet can reach it.
- **No field-level encryption** of names or phones: it would break name search and the key would sit on the same machine anyway.
- **Whole-database encryption (SQLCipher)**: because the system now stores health forms, the whole database file is encrypted at rest, whichever hosting is chosen. Search keeps working. It protects against the file or a disk snapshot leaking; it does not protect against someone with full access to the running machine, so who has access to the host matters as much as the encryption.

**Backups**

1. On every app startup and every day at 22:00 (if running), the app makes a consistent copy of `gym.db` using SQLite's backup API (not a plain file copy while in use).
2. The copy is encrypted with a backup password (AES-256, e.g. an encrypted zip) and named `gym-backup-2026-10-07.zip`.
3. It's written to the Google Drive for desktop sync folder, which uploads it automatically.
4. The app keeps the last 30 backups plus one per month, and deletes older ones.
5. The dashboard shows "Last backup: today 09:02" and turns red if no backup succeeded in 2 days.

**Keys to keep off the PC** (printed in the manager's office or in a password manager)

- The BitLocker recovery key.
- The backup encryption password. Without it, backups can't be restored.
- The manager's PIN (the manager can reset instructors' PINs).
- The Cloudflare account login (domain and tunnel).

**Restore** is a menu action: choose a backup file, enter the backup password, and the app replaces the current database after saving a copy of it. Test a full restore once before going live.

**Privacy**: store only name, phone, notes, an optional photo and the health form. Health information belongs only in the health form, never in the free-text notes; the notes field says so in the interface. Archived customers can be fully deleted on request, which removes their photo, personal fields and linked phones while keeping anonymous visit counts.

## UI demos

Five views cover the whole system: the customer's phone pages, the admin dashboard, the customer page, the prices screen, and the report preview. Names and numbers below are sample data.

### Customer: phone pages

&#91;embedded content: customer phone pages · link, choose a plan, status, sample prices\]

The link page appears only on a phone that isn't linked yet; the plan page only at the first check-in of a month with no plan. Every other scan goes straight to the status page (or "Already checked in"). Pages are mobile-first, with large text and no login form.

### Admin: dashboard

&#91;embedded content: admin dashboard · sample data\]

The home screen, as the manager sees it. Instructors don't get the Reports, Prices, Staff or Settings menus, or the report card. The report card shows where the latest month's report stands (generated, emailed to the manager, approved, sent); the backup card turns red if no backup succeeded in 2 days. "Locked · Unlock" opens the PIN prompt for edit mode.

### Admin: customer page

&#91;embedded content: admin customer page · sample data\]

Everything about one customer in one place. Buttons that change data (check in, link a phone, unlink, change or clear a plan, freeze, edit profile) appear according to the logged-in staff member's role (see Users and roles). "Link a phone" shows the 6-digit code for the customer to enter on their phone; "Linked phones" lists each device with an Unlink button.

### Admin: prices

The manager's price table, one row per plan with an adult and an under-18 price (sample prices; the real ones come from the manager):

| Plan | Adult (₪) | Under 18 (₪) | Valid from |
| --- | --- | --- | --- |
| Monthly | 250 | 200 | Nov 2026 |
| Tri-monthly | 650 | 520 | Nov 2026 |
| Single entry (per visit) | 40 | 30 | Nov 2026 |

Editing a price asks which month it applies from and keeps the old row, so past months are unaffected. The screen also shows upcoming changes and the price history.

### Admin: report preview

&#91;embedded content: monthly report preview · sample prices\]

The Reports screen opens on the latest month with its status line. "Regenerate" rebuilds it after a data fix; "Approve and send" emails it to the recipients in Settings. Any past month can be opened and regenerated with the same result.

## Open questions

Each answer replaces an *assumption* above; none of them changes the architecture, so building can start before they're settled.

**For the manager**

- [ ] Prices: the adult and under-18 price for each plan (placeholders until then).
- [ ] Under 18: is age checked on the 1st of the month, or on the day the plan is chosen?
- [ ] A customer who doesn't come in at all during a month: really not charged?
- [ ] Tri-monthly: once chosen, can the customer switch plans before the 3 months are up?
- [ ] Freezes: do they push a tri-monthly period forward? Any minimum or maximum length?
- [ ] Report: the manager's email, and the recipients who get it after approval.
- [ ] Should the report show the plan type as an extra column, to make checking it easier?
- [ ] Photos: do we want them at all?
- [ ] Health form: which official form to copy, how long it stays valid, and whether minors need a parent's signature.
- [ ] Health form: confirm that instructors see only valid / expired, and only the manager opens the contents.
- [ ] Punch cards: number of entries, price (and under-18 price), expiry, who records the purchase, whether unused entries carry over, and whether single entry is still needed.

**Setup**

- [ ] Hosting: the village's server or a paid VPS (about ₪200/year) instead of the gym PC. Waiting on the village's server manager: own VM or shared machine, root and Docker, SSH access, open ports, uptime, and who else can access the data. If it moves to a server, the Architecture, Security and Operations sections change (Docker, a reverse proxy, admin access through Cloudflare Access, off-server backups).
- [ ] Which domain to buy for the check-in address, and who owns the Cloudflare account.
- [ ] Does the gym PC have Windows Pro (for BitLocker)? Which Google account owns the backup folder and sends the report emails?
- [ ] How reliable is the gym's internet? Frequent outages would mean more manual check-ins and delayed report emails.

**Roles**

- [ ] Confirm the instructor/manager permission split in Users and roles. Anything missing that instructors should or shouldn't do?

## Implementation plan

Build in six milestones, each usable and testable on its own; hand them to Claude Code one at a time.

1. **Foundation**: project layout, settings, SQLite schema and migrations, first manager account on first run, staff accounts with roles and server-side permission checks, the activity log, and the two app entry points (admin and public) sharing one core package.
2. **Customers, prices and plans**: customer create/edit/archive with date of birth, the price table with valid-from months, plan choices and corrections, freezes, and the monthly plan logic, with unit tests for every rule in Plans, prices and billing.
3. **Phone linking and check-in**: link codes, device sessions and the login cookie, the public check-in, link, health form and plan-choice pages, status pages, the health-form block, double-check-in guard, rate limiting, and manual check-in with plan selection and paper-form upload.
4. **Admin screens**: dashboard with live check-ins and expiring health forms, customer list with search, customer page with linked phones, health-form status and plan history, prices screen, settings, staff accounts, lock screen, menus filtered by role. Test every manager-only action as an instructor and confirm it's refused.
5. **Report**: payment calculation from plan choices and check-ins, Excel and PDF export, automatic generation on or after the 1st, email to the manager, Approve and send to recipients, regenerate. Unit tests with fixed sample data for each plan, age group and edge case.
6. **Operations**: encrypted backups and restore, Windows services for both apps and `cloudflared`, the named Cloudflare tunnel on the gym domain, SMTP setup, a printable wall-QR page, and a setup guide for the gym PC.

**Notes for Claude Code**

- Suggested layout: `app/core` (database, models, plan and price rules, reports, email), `app/admin` (routes, templates), `app/public` (routes, templates), `tests/`.
- Run locally: admin with `uvicorn app.admin.main:app --host 127.0.0.1 --port 8000`, public with `uvicorn app.public.main:app --host 127.0.0.1 --port 8001`.
- Test on a real phone before the domain exists with a temporary quick tunnel: `cloudflared tunnel --url http://127.0.0.1:8001`.
- Never bind either app to `0.0.0.0`, and never register admin routes on the public app.
- Keep the login only in the server-set `gym_device` cookie; no `localStorage`.

**Testing priorities**: the report calculation, the subscription status logic, and the linking and cookie flow carry the real risk, so they get the most tests. Test the cookie on an iPhone with Safari specifically. Run a two-week pilot alongside the current process and compare the first real report by hand before switching over.

## Alternatives considered

Two other setups were weighed and set aside; both reuse the same data model, plan and price rules, and report.

| Option | How it works | Why not chosen |
| --- | --- | --- |
| Personal QR + desk scanner | Each customer carries their own QR (phone screenshot or card); a USB scanner at the desk reads it; the status shows on the desk screen | Works fully offline and needs no domain, but customers get no status on their own phone |
| Cloud server | The whole system runs on a rented server; the gym PC uses it in a browser | Customers could check from home, but it costs about $5–6/month, the admin also needs internet, and the system must be hardened as a public server |

If the personal-QR option is ever revisited: QR tokens must be digits only. A keyboard-mode scanner types characters as keystrokes, and with the Hebrew keyboard layout active, letters arrive as Hebrew characters.
