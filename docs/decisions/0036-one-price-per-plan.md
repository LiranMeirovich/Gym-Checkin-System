# 0036. One price per plan, without an under-18 price

- Status: Accepted
- Date: 2026-11-08

## Context
Each plan had two prices, adult and under 18. The customer's age on the 1st of the month picked one, and it was copied onto the choice with its `age_group` (decisions 0024, 0026, 0032). In November 2026 the manager dropped the under-18 prices: every customer pays the same.

The system isn't live, so no real price or choice depends on the split. Dev and demo databases do hold under-18 price rows, and the migration has to run on them.

## Options
- **Under-18 price rows in an existing database:** delete them and keep the adult rows as each plan's price / refuse to upgrade while any exist. Refusing protects history, but it breaks every dev and demo database for rows no one was ever charged.
- **The column:** drop `age_group` from `prices` and `plan_choices` / keep it, always `adult`. A column that can only hold one value is dead weight in every query, constraint and API shape.
- **The API:** remove `age_group` from requests and answers / keep it as an ignored or optional field. Nothing outside our own two React builds calls the API.

## Decision
- **One price per plan**, the same for every customer. `price_for(plan, month)` and `plan_options(month)` no longer take an age group or a customer.
- **`age_group` leaves `prices` and `plan_choices`**, with its CHECKs and its place in the price index. A "no plan" row is now simply one with no plan and no price.
- **The migration deletes the `under_18` price rows.** The adult rows keep their ids and amounts. Every existing choice keeps the price that was copied onto it. Its downgrade restores the column, with `adult` on every price and real choice, but not the deleted rows.
- **The admin API drops `age_group`** from price saves, the price table, plan options and choice rows. A refused price is named by its plan (`monthly`), not `monthly.adult`.
- **Date of birth stays required.** It still decides the health form's version: a parent or guardian signs for someone under 18 on the signing day (decision 0031). `ADULT_AGE` now lives in `app/core/health_forms.py`.

## Consequences
- This supersedes the age-group parts of decisions 0024 and 0026, and 0032's "customers see only their own prices (adult or under 18)". Each customer still sees only the plan page's prices, which are now the same for everyone.
- The design doc's "under 18 on the 1st of the month" assumption and its open question are gone.
- Deleting price rows breaks "history is never overwritten" once, deliberately, before launch. A later change like this on a live database would need a new price row from a month on, not a delete.
- Old activity-log entries for prices and choices still show `age_group`. The log is append-only, so they stay as they were written.
- If an age-based price ever comes back, it's a new feature with its own column and migration. Punch cards (upcoming) start without one.
