# 0026. Plan corrections: "no plan" rows, current-month choices only

- Status: Accepted; its age-group parts superseded by [0036](0036-one-price-per-plan.md) (one price per plan)
- Date: 2026-11-03

## Context
Feature 4 of milestone 2 (decision 0022) lets the manager change or clear a customer's plan choice (`plans.correct`). Decision 0025 made `plan_choices` append-only: a correction is a new row with `replaces_id`, so a change of plan is one insert. Clearing ("this month has no plan after all") had no shape yet, since nothing can be deleted. Two more things needed settling: which choices may be corrected, given that past reports must regenerate identically, and how the route expresses a clear.

## Options
**Clearing**
- **A "no plan" row in `plan_choices`**: it replaces the choice and has no plan, age group or price. The existing unique `replaces_id` and same-customer trigger already cover it. But `plan` becomes nullable, and every reader must treat a "no plan" row as covering nothing.
- **A separate `plan_clears` table** pointing at the cleared choice. `PlanChoice` always has a plan, but "replaced at most once" then spans two tables and needs more triggers, and the history is in two places.

**Which choices can be corrected**
- **Any active choice covering the current month**: this includes a tri-monthly period that started earlier, whose first month is in a past report, so regenerating that report would change.
- **Only a choice whose start month is the current month**: past months are never touched. A tri-monthly period from an earlier month can't be stopped.

**Route**: one route where `plan: null` means clear, or separate change and clear routes.

## Decision
- **Clearing is a "no plan" row** in `plan_choices`: `plan`, `age_group` and `unit_price_agorot` are NULL, and `replaces_id` is required. It takes the months of the choice it clears and covers none of them, so they can be chosen again. This was the developer's choice.
- **Only a choice starting in the current month can be corrected or cleared**, following decision 0025's "staff choose for the current month only". A correction starts in the same month as the choice it replaces. A "no plan" row can't itself be corrected; the manager chooses a plan for the month instead.
- **A correction is priced like a choice**: this month's price for the customer's age group, refused if it isn't set. Clearing needs no price. A correction that would give the same plan, age group and price is refused (`no_change`), but the same plan at a since-corrected price is allowed.
- **The database backs this up**: a CHECK makes a row either complete or a "no plan" row that replaces another; the overlap trigger ignores "no plan" rows; a new trigger keeps a correction on the start month (and a "no plan" row on the whole period) of the choice it replaces.
- **One route**: `POST /api/customers/{id}/plan/corrections` with `{replaces_id, plan}`, where `plan: null` (sent explicitly) clears. A stale page gets `choice_replaced` with the id of the row that replaced the choice.
- **Activity log**: `plan.correct` and `plan.clear`, with the replaced row as `before` and the new row as `after`.

## Consequences
- History stays one chain in one table: every row a customer ever had, and what replaced it (`replaced_by_id` in the API).
- Code reading `plan_choices` must treat `plan IS NULL` as covering nothing. In `app/core/plans.py` that's `_first_active()`, the one place coverage is worked out; the report (milestone 5) must use the same rule.
- A customer who leaves partway through a tri-monthly period that started in an earlier month keeps it; stopping one would change a past report. If the manager needs that, or needs to fix last month before approving its report, it's a rule change for milestone 5, once reports and their approval exist.
- Changing single entry to monthly covers the whole month, visits already made included: the report bills only the active choice (the case decision 0017 deferred to this route).
- `downgrade()` of the migration refuses while "no plan" rows exist, rather than delete history.
