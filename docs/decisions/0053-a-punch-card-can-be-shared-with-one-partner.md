# 0053. A punch card can be shared with one partner, linked by the manager at the desk

- Status: Accepted (to build later: not part of milestone 6)
- Date: 2026-11-25

## Context
The gym wants a punch card to be usable by up to two people: the buyer and one other member, ideally family. Punch cards belong to one customer today (decisions 0042, 0043): one active card at a time, never alongside a plan, the balance counted from the check-ins charged to the card.

## Options
- **The manager links the two at the desk**: on the buyer's customer page, the manager picks the partner. Small (existing staff screens and permissions), both people present so both agree, nothing new on the public app. Someone has to come to the desk, once per card.
- **The buyer shares from the phone with a one-time QR or code**: self-service, but a new public route that hands out access to a paid card, so it needs hashed, short-lived, single-use codes, rate limits and an "undo" screen. About the size of phone linking, and a protected area.
- **The partner picks "use X's card" at check-in**: rejected; anyone could spend someone else's card.
- **Enforcing "family only" in the system**: rejected; surnames prove nothing, and a family-relations system is a lot of work for little gain.

## Decision
The manager links them at the desk. The phone option can come later on the same data if it's asked for.

- **Up to two people**: the buyer and one partner. Both check-ins count against the card's entries, the same day included.
- **Fixed once used**: the partner can't be changed for the card's life. The manager may remove a partner only before the partner has checked in on the card (a mistake); after that the link is permanent. Both linking and removing are logged.
- **One at a time**: while the card is active, the partner has no plan and no card of their own; the card covers them and the plan page doesn't appear.
- **Manager and owner only**: linking gives someone entries another person paid for, a money decision like choosing a plan, which instructors never do (decision 0017). It also makes the manager the "family" check, since it stays a gym policy, not a system rule.
- **Each person still needs their own valid health form** (decision 0004).
- **Report**: the buyer's row shows the price; the partner gets a row with payment 0, marked as a shared card of the buyer, with the card's end date, so the manager sees they trained.

## Consequences
- A schema change (the card's partner, and who linked or removed them) and a change to the check-in order, punch card rules and report: protected areas, built as its own feature after the server work, with `/migration`.
- Amends decisions 0042 and 0043 (a card belongs to one customer) and 0044 (the report's rows).
