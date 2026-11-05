# 0033. Manual check-in, doctor's notes and the health form on the admin PC

- Status: Accepted
- Date: 2026-11-05

## Context
Feature 4 of milestone 3 (decisions 0028, 0031) covers the desk: staff check a customer in by hand, add the doctor's note a "yes" form needs before it counts (decision 0031), and let a customer without a smartphone fill in the health form at the gym. Several things weren't settled:
- what an instructor's check-in records when the month has no plan and the single-entry price isn't set (left open by 0032);
- where the form at the desk runs;
- how doctor's notes are stored;
- which permissions cover all this;
- whether filling in the form at the desk is logged.

## Options
- **The form at the desk**: a gym tablet with its own token or device session vs **the admin app on the front-desk PC**, opened by a logged-in staff member.
- **An unset single-entry price**: let the instructor's check-in through without a plan vs **refuse it** (`price_not_set`).
- **Doctor's notes**: a column on `health_forms` vs **their own append-only table**; store the upload as sent vs **re-encode it**.
- **A rule that a note is at most 3 months old** (the official form's wording): enforce it now vs **not until needed**.
- **Logging the form signed at the desk**: unlogged like the phone vs **logged with the staff member who opened it**.

## Decision
- **The form runs in the admin app on the PC** (no tablet or token for now; a tablet may come later). After adding a customer whose "no smartphone" box is ticked, the admin app opens the form on a screen without the staff header. The customer signs, and the app goes back to the customer page. While the form is missing, the customer page and the check-in dialog link to the same screen. The routes are `GET`/`POST /api/customers/{id}/health-form/fill-in`, which reuse `check_form()`, `save_form()` and the phone's request and response shapes. The PC never gets a `gym_device` cookie, so it never becomes the customer's device.
- **Signing at the desk is logged** as `health_form.fill_in`, with the staff member and the customer's id, never the answers. The phone path stays unlogged (decision 0021: the log is for staff actions).
- **Manual check-in** is `POST /api/customers/{id}/check-in {plan?}`, logged as `checkin.manual`. It checks the health form, the 10-minute repeat and the plan, as the phone does. The manager may pick a plan for a month with no plan. An instructor may not; their check-in records single entry (decision 0017). If the single-entry price isn't set, it is refused with `price_not_set`; in practice the price is always set.
- **Doctor's notes have their own append-only `doctor_notes` table** (JPEG or PNG, at most 5 MB, with the staff member who added it). A "yes" form counts once it has a note. Every upload is re-encoded to a JPEG at most 2500 px on its longer side, with EXIF stripped, and checked before any database work (decision 0027). The admin app shrinks the photo in the browser first. Opening a note is manager-only and logged.
- **No age rule for notes** until the manager asks for one.
- **Permissions**: `health_forms.add_doctor_note` and `health_forms.fill_in` (both roles) replace the planned `health_forms.upload_paper`.
- **The form's React page is shared** (`frontend/src/shared/`). Each build passes its own load and submit functions, and shared code may import neither app (ESLint).

## Consequences
- A customer without a smartphone can register, sign and check in without paper.
- **The auto-lock can interrupt a slow customer.** The admin app locks after the role's idle time without an API request (5 minutes for a manager by default), and filling in the form sends none, so a lock loses what was typed. To revisit if it happens in practice.
- A note added by mistake can't be removed; withdrawing one would be a new kind of row.
- Renewing an expired form for a customer without a smartphone still means opening the PC form by hand. A proper renewal flow is left for later.
- A migration that rebuilds `doctor_notes` must re-create its triggers.
