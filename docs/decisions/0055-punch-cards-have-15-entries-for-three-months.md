# 0055. A punch card has 15 entries and lasts the month it was bought plus two more

- Status: Accepted (to build later: not part of milestone 6)
- Date: 2026-11-25

## Context
The gym changed the card's terms. Decisions 0042 and 0043 set 20 entries, and expiry on the 1st of month X+2 for a card bought in month X (valid for the rest of that month and the next).

## Options
Only one: these are the gym's terms, not a technical choice. What matters is keeping the rule in one place and old cards correct.

## Decision
- **15 entries** per card.
- **Valid until the end of month X+2**: bought on any day of January, it counts through 31 March and has expired on 1 April. Unused entries are still lost.
- The rest of 0042/0043 stands: the price and dates are fixed on the card when it's bought, and the server tells the screens the card's size and dates (React never works them out).

## Consequences
- The size lives in two places, `CARD_ENTRIES` and the `checkins_card_entries` trigger, and the expiry in a CHECK on `punch_cards`: one migration changes all three (`/migration`, protected area). With no production data yet, no existing card needs converting.
- The report's "0 row next month while entries remain" rule (decision 0044) now spans up to two following months.
- Supersedes the size and expiry parts of decisions 0042 and 0043.
