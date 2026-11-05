# 0032. Phone check-in: one route, an append-only `checkins` table, plan chosen with the check-in

- Status: Accepted
- Date: 2026-11-05

## Context
Feature 3 of milestone 3 (decision 0028) lets a linked phone check in from the wall QR. The design doc's order is: linked phone → valid health form (decision 0004) → a plan for this month → checked in, and a second check-in within 10 minutes is only "already checked in". At the first check-in of a month with no plan, the customer picks one on the phone, and that tap completes the check-in. Several things weren't settled: the `checkins` table's exact shape, the route contract, when the page sends the check-in, whether the customer's own plan choice is logged, what happens when a price isn't set, and which prices a customer sees.

## Options
- **Table**: the design doc's `entered_by` vs `staff_user_id` (as on `plan_choices`); rows editable vs **append-only**; storing the plan choice a visit was billed under vs not.
- **Route**: one `POST /api/check-in` with an optional plan vs a separate `POST /api/plan` followed by a check-in.
- **When**: the page sends the check-in as soon as it opens vs a "Check in" button.
- **The customer's choice**: written to the activity log vs not.
- **An unset price**: the plan is shown as unavailable vs the check-in goes through without a plan.
- **Prices shown**: the customer's own age group only vs the whole price table (a new route).

## Decision
- **`checkins` is append-only** (triggers refuse UPDATE and DELETE): `customer_id`, `checked_in_at` (UTC), `method` (`phone` / `manual`), `device_session_id` (phone only), `staff_user_id` (manual only). A CHECK requires exactly the source its method needs, and a trigger keeps a phone check-in on its own customer's phone. The whole table is built now, so manual check-in (feature 4) needs no migration. No plan choice is stored: a correction (single entry to monthly) changes which choice is active, and the report reads that from `plan_choices`.
- **One route**, `POST /api/check-in` with `{plan?}`. The plan is chosen and the visit recorded in one transaction, so a plan is never chosen without its check-in. The answers: 200 `checked_in` / `already_checked_in` with the plan covering the month; 401 `not_linked`; 409 `health_form_required`, `plan_required` (with this customer's options) or `price_not_set`. A plan sent for a month that is already covered is ignored.
- **The page checks in as soon as it opens** (a POST from React; a GET never checks anyone in), and also straight after linking or signing the form. That is the design doc's "one scan".
- **A 200 refreshes the `gym_device` cookie** (same token, a new year) and the device's `last_seen_at`, including for `already_checked_in`.
- **The customer's own plan choice** (`choose_plan_by_customer()`, `chosen_by = customer`) **and their check-in are not logged**: the activity log is for staff changes (decision 0021).
- **A plan whose price isn't set can't be tapped.** If none has a price, the page sends the customer to the desk and nothing is recorded; the instructor's manual check-in is feature 4.
- **Customers see only their own prices** (adult or under 18), on the plan page. No route for the whole price table.
- The 10-minute window counts the customer's check-ins by any phone or method, only within the same Israel month, and is checked before the plan. A visit just after midnight on the 1st is never a repeat of the evening before, so the new month's plan page still shows. One reading of the clock drives the whole check-in (form day, month, window, plan choice), so a tap at midnight can't split them across two months.

## Consequences
- Check-ins can't be edited or voided, even a fake one; voiding would be a new kind of row.
- Reloading the page within 10 minutes records nothing; reloading after 10 minutes records another visit, which single entry bills. That is the design doc's rule.
- Tapping a plan fixes it for the month without a confirm step; only the manager can correct it.
- A migration that rebuilds `checkins` must re-create its three triggers (`tests/test_models_checkins.py` checks them).
- Punch cards can add a nullable `checkins.punch_card_id`, and their "active card" step goes between "a plan covers the month" and the plan page.
- Feature 4 still decides what an instructor's single-entry fallback records when the single-entry price isn't set.
