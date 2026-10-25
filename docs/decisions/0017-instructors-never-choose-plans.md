# 0017. Instructors never choose plans; their check-in falls back to single entry

- Status: Accepted
- Date: 2026-10-25

## Context
A customer's first check-in in a month needs a plan covering that month. On the phone the customer picks it. At a manual check-in the design doc had the check-in dialog ask the staff member to pick one, and let instructors set a plan where there was none (but not change one). The developer wants instructors to deal with subscriptions as little as possible: plans affect what the customer is billed, and the manager is the one who should settle them.

## Options
- **Instructors pick the plan at a manual check-in (the design doc's original rule)**: the month always gets the plan the customer asked for. But instructors make billing choices, and the plan code must stop an instructor's "choose" from overwriting a plan that's already there.
- **The month stays without a plan until the manager fills it in**: instructors never touch plans. But the manager has to find and fill every empty month before the report goes out.
- **An instructor's check-in records single entry**: instructors never touch plans, the visit is counted and the month is never left empty. A customer who wanted another plan asks the manager to change it.

## Decision
An instructor's manual check-in for a customer with no plan that month records **single entry** for that month (chosen by staff, with the instructor recorded). Picking a plan (`plans.choose`) and changing one (`plans.correct`) are manager-only. When the manager checks someone in manually, the dialog still asks them to pick a plan. The design doc ("Users and roles" and "The monthly choice") now says this.

## Consequences
- The fallback is check-in logic (milestone 3), not a permission: `checkins.manual` is all the instructor needs, and the check-in code records single entry when no plan covers the month.
- Once single entry is recorded, the month has a plan, so the customer's phone doesn't offer the plan page for it. Changing it goes through the manager.
- A customer who meant to pay monthly is billed per visit until the manager corrects it, so the report depends on the manager acting on those requests.
- Deferred to the change-plan route: the manager will likely want a change from single entry to monthly to cover the whole month, including the visits already recorded. Corrections add a new row and keep the single-entry one (history is never overwritten), and the report must regenerate identically for past months.
