# 0035. Customers can sign up on their own phone

- Status: Accepted
- Date: 2026-11-08

## Context
Until now, only staff added customers (decision 0023), and a phone was linked with a 6-digit code from the desk (decision 0029). The developer wanted a new customer to be able to start on their own phone. This was split from milestone 3's fourth feature (decision 0028) and built after the styling pass (decision 0034).

It touches customer login (a protected area), so a few choices had to be made:
- What happens when the number is already a customer's.
- Whether sign-ups are marked or logged.
- Whether the gym can switch the feature off.
- How much the answer may reveal.

## Options
- **A number that is already a customer's:** bring an inactive customer back, as the desk does / refuse every existing number, active or not. Reactivating from the phone would let anyone take over a former customer by typing their number.
- **Marking sign-ups:** a `customers.self_registered` column (a migration) / nothing. A mark would let the dashboard list phone sign-ups apart from desk ones, but staff already know whom they added, and the newest customers are a plain query on `created_at`.
- **An on/off setting for the manager:** a gym setting / none. There's no use case for turning it off.
- **The refusal's wording:** one vague answer for everything, as linking does (decision 0029) / say plainly that the number is taken. A vague answer can't hide anything here: an unknown number succeeds and logs the phone in, so the two answers always differ.
- **Proving the number belongs to the person:** an SMS code / a desk code / nothing for now.

## Decision
- An unlinked phone at `/c` can sign up: first name, last name, phone and date of birth, under the same rules as `add_customer()` (no notes). The customer, a device session and the `gym_device` cookie are created in one transaction (`phone_links.sign_up()`, `POST /api/sign-up` on the public app). The phone then goes through the normal flow: health form, plan, check-in.
- A number that belongs to any customer, active or not, is refused with 409 `phone_taken` and "go to the desk". Only staff bring an inactive customer back. The answer never says which customer.
- The sign-up is **not logged**: no staff member made it, like a customer linking their own phone (decision 0029).
- **No column and no setting.** Milestone 4's "latest sign-ups" are the newest customers by `created_at`.
- **The number isn't verified.** We accept that the refusal tells anyone whether a number is a customer's. The edge rate limit planned for linking (decision 0029) covers this route too. An SMS check, or a desk code for sign-up, may come later (the developer's call).

## Consequences
- Decision 0029's rule that the public app "never says whether a number is a customer's" now holds for linking only, not for sign-up.
- Anyone with a photo of the wall QR can create a customer, sign the health form, pick a plan and check in. That customer then appears in the month-end report. Staff see every check-in live, and the manager approves the report before it's sent; a customer created by mistake can only be deactivated, never deleted (decision 0021).
- Someone can sign up with another person's number. The real person is then told to go to the desk, and staff fix the wrong customer's phone number first, because a number belongs to one customer.
- The Cloudflare rate-limit rule (milestone 6) must cover `POST /api/sign-up` as well as `POST /api/link`.
