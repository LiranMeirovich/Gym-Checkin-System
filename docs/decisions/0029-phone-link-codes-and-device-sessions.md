# 0029. Phone link codes: short-lived and single use, no lockout, rate limiting at the edge

- Status: Accepted
- Date: 2026-11-04

## Context
A customer links a phone once (design doc: "Check-in flow"). Staff press "Link a phone" on the customer's page, the admin app shows a 6-digit code, and the customer types their phone number and the code on the public page. If they match, the server creates a device session and sets the `gym_device` cookie. The public app is the one reachable from the internet, so the link route is the place someone could guess.

The design doc asked for a 10-minute code, a lockout after 5 wrong codes per phone number (15 minutes, also in decision 0023's context), and IP rate limiting inside the public app. The developer's view: the code is only something the instructor reads out at the desk, so it doesn't need heavy protection. It's enough that it's used once and expires quickly. They also preferred rate limiting in front of the server rather than in the app code.

## Options
- **Code storage: plain SHA-256** (like session tokens) vs a slow hash (Argon2id, like PINs). A 6-digit code has only a million values, so a slow hash wouldn't stop anyone holding the database; what protects it is the short lifetime and single use. SHA-256 keeps it simple.
- **Wrong codes: per-number lockout** (design doc) vs **no guard at all**. A lockout needs a counter on the code or number, and lets anyone lock a customer out by typing their number. With no guard, the only protections are the code's lifetime, single use and an edge rate limit.
- **IP rate limiting: in the app** vs **at the edge** (a Cloudflare rule in front of the tunnel). In the app it needs shared state and the `CF-Connecting-IP` header; at the edge it's configuration, and it stops requests before they reach the gym PC.
- **A 4th phone: refuse** vs **unlink the least recently used one**.

## Decision
- Codes are 6 digits from `secrets`, stored as SHA-256, valid for **15 minutes**, used **once**, and only the customer's **newest** code counts (issuing a new one cancels the old).
- **No wrong-code lockout** and **no rate limiting in the app**. IP rate limiting for `POST /api/link` is an edge (Cloudflare) rule, set up with hosting.
- Every refusal (unknown number, wrong, used, old or expired code, inactive customer) is the **same answer**, so the page never reveals whether a number belongs to a customer.
- Up to **3 phones** per customer; linking a 4th **unlinks the least recently used**. Linking again in the same browser replaces that browser's old session.
- A device session ends when staff unlink it, when it goes **a year** without use, or when its customer is deactivated. Only the token's SHA-256 hash is stored.
- The public app has no CSRF token: it refuses writes that don't come from its own origin (the same-origin middleware, now shared from `app/core/http.py`). The cookie is `SameSite=Lax` as well.
- Issuing a code and unlinking a phone are staff changes and go to the activity log. A customer linking their own phone, and the automatic unlink of a 4th phone, are not logged.

## Consequences
- The schema is simpler than the design doc's: `link_codes` has no `failed_attempts`; it records who issued the code (`created_by`).
- Until the edge rule exists, nothing limits how fast someone can guess. A guess must hit a 15-minute window while a code is live for that number, roughly 1 in a million per try, but the edge rule is required before launch (hosting follow-up).
- Decision 0023's lockout reasoning no longer applies; its other reason for normalising numbers (one customer per number, `find_by_phone()`) stands.
- The same-origin check behind cloudflared relies on the proxy sending `X-Forwarded-Proto: https`; if it doesn't, compare against the configured public hostname instead. Checked in milestone 6 with the rest of deployment (decision 0030).
