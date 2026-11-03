# 0025. Plan choices are append-only rows, linked by `replaces_id`

- Status: Accepted
- Date: 2026-11-03

## Context
Feature 3 of milestone 2 (decision 0022) adds the `plan_choices` table: what a customer chose for a month, at what price, and who chose it. A customer-month may have at most one active choice, or a customer could be billed twice. History is never overwritten (a hard rule), so feature 4's corrections add a row instead of changing one. The design doc sketched a `replaced_by` column on the old row and `chosen_by` as customer / admin. Two more things weren't settled: which months staff may choose for, and what happens when the plan's price isn't set (decision 0024 ships no prices).

## Options
**Table shape**
- **One row per choice** (the design doc): a tri-monthly choice is one row from `start_month` to `end_month`. A range can't be a unique index, so overlaps need a trigger.
- **One row per covered month**: tri-monthly is three rows (price, ₪0, ₪0), and a partial unique index on `(customer_id, month)` enforces the rule. But the three rows must always be created and corrected together.
- **One row per customer-month, set to "no plan" and later changed**: this updates rows in place, which breaks the history rule, and needs a row for every customer each month.

**Linking a correction**
- **`replaced_by` on the old row** (the design doc): the new row must exist before the old one can point at it, and while the old one is still active the overlap trigger refuses the new row. It only works with a deferred foreign key and an id reserved in advance, or without the insert trigger.
- **`replaces_id` on the new row**: a choice is active while no row replaces it. A correction is one insert, and rows are never updated.

**Overlap check**: in the plan code only, or in the plan code backed by a database trigger.

## Decision
- **One row per choice**, as in the design doc. This was the developer's choice.
- **Rows are append-only.** Triggers refuse UPDATE and DELETE, and a correction is a new row with **`replaces_id`** pointing at the choice it replaces. `replaces_id` is unique, so a choice is corrected at most once.
- **At most one active choice per customer-month** is checked in `app.core.plans`, which returns a clear error naming the covering choice. A trigger refuses an overlapping row as a backstop, and another trigger refuses a correction of another customer's choice.
- **`chosen_by` is `customer` or `staff`**, plus a nullable `staff_user_id`. A CHECK requires it when staff chose and forbids it when the customer did, so an instructor's single-entry fallback (decision 0017) names the instructor on the row itself.
- **Staff choose for the current month only** (the gym's month, not UTC's). This was the developer's choice.
- **A price that isn't set refuses the choice** (`price_not_set`), and `unit_price_agorot` stays required. Nothing guesses an amount.

## Consequences
- History can't be edited even by a buggy query, and past reports can always regenerate.
- "Active" is a `NOT EXISTS` lookup (indexed by the unique `replaces_id`) rather than a column. `covering_choice()` in `app/core/plans.py` is the one place coverage is worked out.
- The triggers live only in the migration, as with `activity_log`. A migration that rebuilds the table must create them again, and `tests/test_models_plan_choices.py` checks they exist at head.
- Feature 4 must decide how "clear a plan" is expressed, since nothing can be deleted (likely a replacing row that marks the month as having no plan, which may need a schema change).
- A month missed by everyone can't be filled after the month ends. If the manager needs to fix last month before approving the report, that's a change to this rule.
- Milestone 3 decides what an instructor's single-entry fallback records when the single-entry price isn't set.
- This replaces the design doc's `replaced_by` and `chosen_by (customer / admin)`, and the `replaced_by` mentioned for feature 4 in decision 0022. The design doc is updated to match.
