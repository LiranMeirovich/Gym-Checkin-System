# 0024. Prices start empty, are only added, and all staff can see them

- Status: Accepted
- Date: 2026-10-30

## Context
The Prices feature (decision 0022) needed the manager's price table, with "valid from" months so past months keep their prices. Three things weren't settled. The design doc said the system ships with placeholder prices, while decision 0006 says no real prices in code and that default prices come from settings. The month needed a stored form that plan choices can share. And the design doc kept the Prices screen from instructors.

## Options
- **Starting prices:** placeholder prices seeded by a migration / an empty table the manager fills in before launch.
- **Stored month:** `YYYY-MM` text / a date fixed to the 1st of the month.
- **Which months a change can start from:** any month / the current month or later.
- **Correcting a price:** update the row or forbid a second row for a month / add another row, and the newest wins.
- **Seeing prices:** `prices.edit` covers viewing, so manager only / a separate `prices.view` for all staff.

## Decision
- **The table starts empty.** A placeholder could be copied onto a real customer's choice and charged without anyone noticing. A price that isn't set shows as "not set", and `price_for()` returns nothing rather than an amount.
- **Months are `YYYY-MM` text**, read as `Month` (`app/core/months.py`) in Python. The text sorts in time order and can't hold a mid-month day.
- **A change starts in the current month or up to 24 months ahead.** Past months are refused, so what a past month cost never changes. The upper limit catches mistyped years.
- **Rows are only added.** The latest `valid_from_month` up to a month applies, and among rows for the same month the newest wins, so a correction or a cancelled change is one more row. This is why there's no unique constraint on plan, age group and month. The table doubles as the price history, with `created_at` added for when a row was entered; who entered it is in the activity log.
- **All staff can see prices (`prices.view`); only the manager edits them (`prices.edit`).** Prices aren't secret: customers end up paying them.

## Consequences
- Plan choices (feature 3) and check-in must handle a price that isn't set.
- The manager must enter every price before launch.
- Saving a price for the current month doesn't change choices already made, even when it fixes a typo: they keep their copied price unless the manager corrects the plan.
- Add-only is enforced by the core module offering no update or delete, not by database triggers. Reports stay reproducible because they use the price copied onto each choice.
- Reverting an upcoming change means saving the old amount for that month, so that row still shows under upcoming changes.
- This replaces the design doc's placeholder prices and the "default prices" in decision 0006. The rest of 0006 stands. The design doc is updated to match.
- Instructors seeing prices still has to be confirmed with the manager, with the rest of the permission split.
