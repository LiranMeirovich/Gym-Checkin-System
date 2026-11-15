# 0045. Report delivery: append-only steps, standard-library email, and an hourly "what's due" job

- Status: Accepted
- Date: 2026-11-15

## Context
Milestone 5's third feature (decision 0043) delivers the monthly report (design doc: "Monthly report"). On or after the 1st, last month's report is generated and emailed to the manager without anyone pressing a button. The manager checks it on the Reports screen and clicks Approve and send, which emails it to the recipients in Settings. The dashboard shows where it stands and flags a failed email.

Constraints:
- `reports` is append-only, one row per generation, and delivery steps must not be columns on it (decision 0044).
- Request transactions hold SQLite's write lock (decision 0027), and SMTP can take seconds.
- The PC may be off on the 1st, and the internet may be down.
- Uvicorn runs a single worker.
- Hosting is still open.
- The repo is public, so nothing gym-specific can go in code.

## Options
- **Storage**: one append-only `report_deliveries` table with a `kind` column, or separate approval and email tables. One table makes the status a single read: the newest step of each kind.
- **Email library**: the standard library's `smtplib` and `email`, or a package such as `aiosmtplib`. The routes are synchronous, so async gains nothing.
- **Scheduler**: a plain thread in the admin app, or APScheduler (a dependency). For timing, either a timer for one exact moment, or a periodic "what's due" check.
- **Without SMTP**: in dev, save each email as an `.eml` file in an outbox folder, or treat every email as failed ("not configured").
- **Approve and send**: one action, or two steps (approve, then send).

## Decision
**Storage**
- `report_deliveries` holds one append-only row per step, naming a generation:
  - `kind`: `manager_email`, `approval` or `recipients_email`.
  - `outcome`: `sent` or `failed`, for emails only.
  - `recipients_json`: the addresses at the time of sending.
  - `staff_user_id`: empty for the scheduled job.
- CHECKs tie each column to its kind, and triggers refuse UPDATE and DELETE.
- The downgrade refuses once any step exists, because unlike a report, this history can't be rebuilt.

**Email** (`app.core.email`)
- Built and sent with the standard library: STARTTLS with certificate checks, a 30-second timeout.
- `GYM_SMTP_HOST`, `_PORT`, `_USER` and `_PASSWORD` must all be set or none. They are required in prod, and the user is also the From address.
- In dev without a host, emails are written to the git-ignored `outbox/` folder.
- A failure's cause goes to the server log only.

**Delivery** (`app.core.report_delivery`)
- Only a month's newest generation is delivered. Approve and Send again name the generation the screen showed and are refused if it changed.
- Approve and send is one action. The approval and its log entry are saved in the request, and the email goes out after the response. If the send fails, the approval stays and only Send again is needed.
- Sending runs outside the request lock, with one claim per month, the same pattern as generation (decision 0044).
- Attachments are rebuilt in memory from the generation's snapshot, so the email carries exactly what was approved.

**Scheduled job** (`app.core.report_schedule`)
- A daemon thread in the admin app runs at startup and then hourly. Each run does whatever is due for last month (Israel time):
  1. Generate it if it was never generated, by anyone.
  2. Email the manager if the newest generation is the job's own and its email wasn't sent or failed.
  3. Retry a failed send to the recipients after approval.
- A generation the manager made from the screen is never emailed by the job.
- The job's work isn't logged.
- The developer asked why it runs hourly rather than once a month: a "what's due" check covers a PC that was off on the 1st and an email that failed while the internet was down. It also needs no date maths for clock changes, and costs a couple of reads when nothing is due.

## Consequences
- **No extra dependency.** Gmail with an app password works over STARTTLS on 587. A server that offers only implicit TLS on 465 would need a small change.
- **Prod won't start without SMTP set up**, and that includes any prod trial before hosting is decided.
- **A failed email is retried within an hour** of the cause going away. A timeout after the server had accepted the email can send it twice; that was accepted rather than risk losing an email.
- **Only last month is checked.** A PC off for more than a month never generates the month before on its own, though the manager can still do it from the screen.
- **The first 1st after install emails a report even if it's empty.**
- **Approve and send has no confirmation step.** One click emails outside recipients.
- **The activity log holds the recipient addresses** for each approval.
- **The backups in milestone 6 can add their own "is it due?" check to the same loop.**
- **Tests stub the thread out** (`tests/conftest.py`), and the job's own tests call `run_due()` directly.
