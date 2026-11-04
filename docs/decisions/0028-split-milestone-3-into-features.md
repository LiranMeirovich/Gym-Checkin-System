# 0028. Split milestone 3 into four features, phone path first

- Status: Accepted (feature 4 amended by [0031](0031-health-forms-are-online-only.md): no paper forms; the form is filled in on a gym device)
- Date: 2026-11-03

## Context
The design doc's milestone 3 (Phone linking and check-in) covers link codes, device sessions and the `gym_device` cookie, the public check-in, link, health form and plan pages, status pages, the health-form block, the double-check-in guard, rate limiting, and manual check-in with plan selection and paper-form upload. As with milestones 1 and 2 (decisions 0008, 0022), one feature = one branch = one PR = one session, and most of the milestone is a protected area (customer login, cookie, plan logic, schema), so it has to come in reviewable pieces.

The order is constrained by decision 0004: no check-in without a valid health form. The first proposal therefore started with paper forms uploaded by staff. The developer pointed out that this isn't how forms will normally be collected: a customer who tries to check in without a valid form is shown the form on their phone. Paper upload is only the fallback for customers without a smartphone. That is also what the design doc's Health form section says.

## Options
- **Paper forms first, phone form last**: check-ins become possible early (paper form plus manual check-in). Cons: builds the fallback before the main path, and the phone form ends up bolted on at the end.
- **Phone path first, with the health form as one feature**: builds the flow customers will actually use, in the order they meet it. Cons: the health-form feature is larger (table, status, signature, PDF snapshot), and nobody can be checked in until the third feature lands.
- **Phone path first, health form split in two** (table and status, then the phone form): smaller PRs. Cons: one more feature, and the first half has no way to create a form.

## Decision
Split milestone 3 into these features, built in this order:

1. **Phone linking**: `link_codes` and `device_sessions`; the staff "Link a phone" code (6 digits, 10 minutes, single use) and the linked-phones list with Unlink (at most 3); the public link route that sets the `gym_device` cookie; the wrong-code lockout keyed on the normalised phone number; IP rate limiting on the public app; the public link page.
2. **Health forms on the phone**: `health_forms` (append-only, document stored in the database); validity and the newest valid form; the "valid until / missing" status for staff; the manager opening a form's contents, logged; the phone form with questions, confirmation, name, finger-drawn signature, the guardian version for under-18s, and a PDF snapshot.
3. **Phone check-in and plan page**: `checkins`; one core `check_in()` used by both apps; the public `/c` flow (cookie → health form if needed → plan page → status or "already checked in"); the customer's own plan choice; the 10-minute double-check-in guard; the cookie refresh.
4. **Manual check-in and paper forms**: the staff Check in button; the instructor's single-entry fallback (decision 0017); the manager picking a plan in the dialog; what happens when a price isn't set; the paper-form upload as the fallback.

The official health form isn't available yet, so feature 2 uses **made-up placeholder questions under a form version**; the real questions come in later as a new version.

Each feature ships its `app/core` logic, its JSON routes and a plain, unstyled React page; milestone 4 styles them.

## Consequences
- Each feature starts in a new session with `/start-feature <feature>`; CLAUDE.md's Project status tracks which is next.
- Nobody can be checked in until feature 3. That's acceptable because the system isn't live yet.
- Left out of milestone 3: the public app's host check and security headers (they wait on the hosting decision), the dashboard's live check-ins and expiring forms (milestone 4), and punch cards. `checkins` must leave room for a nullable `punch_card_id` later.
- Before launch, the placeholder questions must be replaced with the manager's official form.
