# 0054. Tri-monthly plans are removed

- Status: Accepted (to build later: not part of milestone 6)
- Date: 2026-11-25

## Context
The gym no longer wants to sell a tri-monthly plan. It's built throughout: a `Plan` value priced on the Prices screen, a plan choice covering three months (decisions 0025, 0026), its own report rule (paid in the first month, 0 in the other two, decision 0044), the phone's plan page and the desk's check-in dialog. The system isn't in use yet, so no real customer has a tri-monthly plan.

## Options
- **Hide it**: stop offering it but keep the value and rules in the code. Less work, but dead rules stay in the protected plan and report logic.
- **Remove it**: the value, its price, its coverage rule and report rule, its screens' option, and the database CHECKs that allow it.

## Decision
Remove it completely, so the plans are monthly, single entry and the punch card. Because there's no production data yet, the migration refuses to run if any tri-monthly row exists rather than rewriting history (dev and demo databases are recreated), as decision 0036 did for under-18 prices.

## Consequences
- Touches protected areas (plan logic, report calculation, schema): `/migration`, and the plan, report and check-in tests that use tri-monthly are removed or rewritten.
- Amends decisions 0025, 0026 and 0044, and 0042/0043's "one at a time, never alongside a monthly or tri-monthly plan" now reads "never alongside a monthly plan".
- Simpler reports: only a punch card is still paid once and covers more than one month.
