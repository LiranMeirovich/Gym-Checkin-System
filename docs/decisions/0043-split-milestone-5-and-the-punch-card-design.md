# 0043. Split milestone 5 into three features, and how punch cards are stored and sold

- Status: Accepted
- Date: 2026-11-11

## Context
Milestone 5 is "Punch cards and report", punch cards first (decision 0042). It needed splitting into features, as milestones 2–4 were (decisions 0022, 0028, 0037), and decision 0042's card rules (20 entries, one price, expiry on the 1st of the month after next, one at a time, never alongside a monthly or tri-monthly plan) needed a storage and flow design. The design doc already settled a `punch_cards` table of its own, with the balance counted from `checkins.punch_card_id`, never stored.

## Options
- **Pricing**: a separate price setting for the card, or a fourth `Plan` value in the existing `prices` table. The table already has the history, the "valid from" months and the Prices screen.
- **Card size and expiry**: a per-card `entries` column and a configurable expiry, or one code constant (20) and the expiry stored on each card.
- **Mistakes**: build card cancellation now, or keep this feature smaller and stop mistakes before they happen with a confirm step on the phone.
- **Where a card is bought**: at check-in only, or also from the customer page like a plan choice.

## Decision
- **Milestone 5 has three features**: 1 Punch cards; 2 Report (the calculation, a manager Reports screen with a preview and Regenerate, Excel and PDF files in `reports/`); 3 Report delivery (generated on or after the 1st, emailed to the manager, Approve and send, the dashboard's report card).
- **Priced as a plan, stored apart**: `punch_card` is a fourth `Plan` value, priced in `prices` like the others, so the Prices screen gets a fourth row. It is never a plan choice: `plan_choices`' CHECK stays at three plans, `app.core.plans` refuses it, and the choose and correct routes answer 400 `not_a_choice`. The API's types for a covering plan and a choice row list only the three plans.
- **One size, expiry on the row**: 20 entries is a code constant (`CARD_ENTRIES`). Each card stores `price_agorot` (copied when bought), `bought_month` and `expires_on`, the 1st of month X+2 in Israel time; a CHECK ties `expires_on` to `bought_month`. Who bought it is `bought_by` (customer / staff) and `staff_user_id`.
- **Enforced in the database too**: `punch_cards` is append-only (triggers), and two triggers on `checkins` refuse a card of another customer and a 21st check-in on one card. Expiry is checked in the core code only: `expires_on` is a local date and `checked_in_at` UTC.
- **Check-in order**: a covering plan, else the active card (one entry, any month, no plan page), else the plan page (with the card as a fourth option) or, for an instructor, single entry. A 10-minute repeat uses no entry. While a card is active, every plan choice and correction is refused with 409 `punch_card_active`, and no second card is sold.
- **No cancellation yet**: instead, tapping any option on the phone's plan page opens a confirm step (the option and its price, Confirm / Back), and nothing is sent until Confirm. The desk is unchanged.
- **Bought only at a check-in**: on the phone, or by the manager in the check-in dialog. The customer page shows the active card and every card bought, but never sells one. Its plan status carries `check_in_options` (the plans and the card) beside `options` (the plans only) for the dialog's picker.
- **Logging**: a staff sale is logged as `punch_card.buy`; the customer's own purchase isn't (decision 0021).
- **The server says the card's size and dates**: a card offer carries `entries` and `valid_until` (the last day a card bought now counts), and a card carries `entries`, `expires_on` and `valid_until`. React never works out the expiry or keeps its own copy of 20 (CLAUDE.md: business rules live only in `app/core`).

## Consequences
- A card cannot be cancelled or refunded yet. A mistaken sale stays until it runs out or expires; designing that with the manager is a follow-up.
- Changing the card size means changing `CARD_ENTRIES` and the trigger (a migration). Old cards keep the old balance rule unless that migration says otherwise.
- The migration refuses to downgrade once a card or a card price exists, so real purchases are never dropped.
- The report (feature 2) must charge a card in the month it was bought and must not count check-ins charged to a card as single entries.
