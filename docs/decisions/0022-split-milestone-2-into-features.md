# 0022. Split milestone 2 into four features, without freezes

- Status: Accepted
- Date: 2026-10-29

## Context
The design doc's milestone 2 (Customers, prices and plans) covers customer create/edit/archive with date of birth, the price table with valid-from months, plan choices and corrections, freezes, and the monthly plan logic. As with milestone 1 (decision 0008), one feature = one branch = one PR = one session, and most of this milestone is a protected area (schema, plan and price logic), so it has to come in pieces small enough to review.

Two more questions came up. The design doc puts the customer list, customer page and prices screen in milestone 4. But since decision 0020 every screen is a JSON route plus a React page, and milestone 4 is now mainly the design and styling pass. The manager also said he probably doesn't want freezes at all.

## Options
- **Milestone 2 as one feature**: matches the doc's wording. Cons: one very large protected-area PR.
- **Five features including freezes**: covers the whole doc. Cons: builds something the manager likely won't use.
- **Four features, freezes dropped for now**: less to build and review. Cons: if the manager wants freezes after all, it's a later feature and a schema change.

For the screens: core and API only until milestone 4, or each feature also ships a plain React page like setup, the lock screen and home.

## Decision
Split milestone 2 into these features, built in this order:

1. **Customers**: the `customers` table; add, edit and archive, with phone normalisation and date of birth; activity-log actions.
2. **Prices**: the `prices` table with `valid_from_month`, the price lookup for a plan, age group and month, and the manager's price edit (a new row, never an overwrite). Introduces the shared month type.
3. **Plan choices and monthly status**: the `plan_choices` table, at most one active plan per customer-month, age group on the 1st of the month, the price copied onto the choice, "what covers this customer this month", and the manager's choice (`plans.choose`).
4. **Plan corrections**: change or clear a plan (`plans.correct`), with a new row and `replaced_by` on the old one.

Each feature ships its `app/core` logic, its admin JSON routes with server-side permission checks, and a plain, unstyled React page like the ones built so far. Milestone 4 adds search, the dashboard, role-filtered menus and the styling.

**Freezes are dropped for now**, because the manager probably doesn't want them. **Customer photos are left out** until that's discussed with the manager; a nullable column is an easy migration later.

## Consequences
- Each feature starts in a new session with `/start-feature <feature>`; CLAUDE.md's Project status tracks which is next.
- All four touch protected areas; features 3 and 4 carry most of the plan-rule tests.
- The `plans.freeze` permission and the design doc's freeze rules, `freezes` table and report's frozen-month ₪0 stay unbuilt. If freezes come back, they're a new feature with their own migration, and the plan-coverage logic must allow a period to be extended.
- The design doc needs updating to match (freezes, photo column, which screens come in milestone 2).
