# 0042. Punch cards come before the report, with 20 entries until the 1st of the month after next

- Status: Accepted
- Date: 2026-11-10

## Context
Punch cards were "upcoming, details pending" (design doc, Punch cards; CLAUDE.md said 12 entries). The manager has now given the details. The report pays out from every kind of plan, so if it were built first, it would have to be reopened for punch cards. The developer also confirmed what the report shows.

## Options
- **Report first, punch cards after**: the original order. The report would need a second round of changes and tests once cards exist.
- **Punch cards first, then the report**: the report is built once, knowing every kind of plan.

## Decision
Punch cards come first. Milestone 5 becomes **Punch cards and report**: punch cards are its first feature, then the report features. The milestone numbers stay the same (6 is still Operations), so earlier records that say "milestone 6" stay right.

**Punch card rules**
- A card has **20 entries**, bought for one price (set on the Prices screen like the other plans). Each check-in uses one entry; the balance counts down from 20 to 0.
- **Expiry is fixed by the month it was bought, not the day**: a card bought on any day of month X is valid until the end of month X+1 and has expired on the 1st of month X+2. Bought on 1 January or 28 January, it expires on 1 March. Unused entries are lost at expiry.
- **Bought like a plan, at the first check-in of the month**: the customer picks it on the phone's plan page, or staff pick it at a manual check-in, by the same rule as plans today (decisions 0017, 0033: the manager picks; an instructor's check-in falls back to single entry).
- **Single entry stays** as it is.
- **One at a time**: a customer can't buy a card while they have an active one, or hold a card and a monthly or tri-monthly plan at once. Someone with a plan never sees the plan page anyway.
- **Across months, like tri-monthly**: an active card that hasn't expired covers the next month too; the check-in just uses an entry, with no plan page.
- **When it runs out mid-month** (0 entries or expiry), the next check-in shows the plan page, as at the start of a month: a new card, monthly, tri-monthly or single entry.
- **The price is copied onto the card when it's bought**, like plan choices' prices (decision 0025). A customer always pays the price shown when they chose; a later price change never touches a card already bought, and past reports regenerate the same.

**Report columns** (one row per customer with something to pay or covered that month): first name, last name, subscription end date (by plan type), payment for this month.
- A tri-monthly plan is paid in full in the month it was chosen; its other two months show 0.
- A punch card is paid in full in the month it was bought; its end date is the card's expiry. The next month shows 0.

## Consequences
- The design doc's plan from "Punch cards" still holds: a `punch_cards` table of its own, the balance calculated from the check-ins charged to it (`checkins.punch_card_id`), never stored, so the report stays reproducible (decision 0032 left room for this). Schema change: follows `/migration`; plan logic is a protected area.
- CLAUDE.md's Project status and the design doc's punch card, report and implementation plan sections are updated to match.
