# 0023. One customer per phone number, an active flag instead of an archive date

- Status: Accepted
- Date: 2026-10-29

## Context
The Customers feature (milestone 2, feature 1, decision 0022) adds the `customers` table and the admin routes to add, edit and archive customers. The design doc gives the columns (phone "unique, normalised", `archived_at`) but leaves open how phones are normalised, whether an archived customer's phone can be reused, whether date of birth is required, what archiving is for, and how long notes may be.

The phone number matters beyond this feature: when a customer links a phone (milestone 3) they type their number and a 6-digit code, and 5 wrong codes lock that number for 15 minutes. The lockout counts per number, so every way of typing the same number must end up as the same stored value.

## Options
- **Phone uniqueness:** unique among active customers only / unique across all customers, archived ones included.
- **Phone format:** the `phonenumbers` library / a few handwritten Israeli rules. Stored as local (`0501234567`) or E.164 (`+972501234567`).
- **Archiving:** an `archived_at` timestamp / an `active` flag, like `staff_users` / no archiving at all.
- **Date of birth:** optional / required when the customer is added.
- **Hiding buttons by role:** send the staff member's permission names to React / React uses the role it already has. Either way the server checks every route.

## Decision
- **A phone number is one person, always.** It's unique across every customer, active or not. Adding a customer with the phone of an inactive one doesn't make a second customer: the API answers with the existing customer, who is reactivated with their history intact. Sharing phones isn't common enough here to plan for (gym members are 13+ and have their own phones).
- **Handwritten Israeli rules, stored as E.164.** Keep only digits and a leading `+`; `+972` / `972` (and a stray `0` after it) becomes `0`; accept `0` + 8 digits (landline) or `0` + 9 digits (`05x` mobile); store `+972` + the number without its `0`. No new dependency. Israel is assumed as the country, and the code says so.
- **An `active` flag instead of `archived_at`.** Deactivating only hides a customer from the default list; their data, plans and log stay, and nothing is deleted (decision 0021). Deactivating needs `customers.archive` (manager). Reactivating is part of adding a customer again, so it needs only `customers.add`. When it happened is in the activity log, so no timestamp column is needed. Search and sorting (for example by last check-in) are queries, not reasons to archive.
- **Date of birth is required when the customer is added**, and the staff member adding them (instructor or manager) sets it. After that only the manager changes it (`customers.edit_birth_date`), since it sets the under-18 price.
- **Notes are free text up to 256 characters**, seen and edited by both roles.
- **React hides buttons by role**; no permission list is added to the session. Every admin route checks its named permission on the server, and each route's tests call it as an instructor.

## Consequences
- The normalised phone is the customer's identity for linking and the lockout, so changing the format later means migrating every stored number.
- A customer can't be added under a phone another customer has, even an inactive one; a wrong number on the old record has to be corrected there first.
- Non-Israeli numbers are refused. A gym outside Israel would need a settings-driven country.
- React's role check copies part of `ROLE_PERMISSIONS`. If the two disagree, the server still refuses; the button just shows when it shouldn't.
- The design doc's data model lists `archived_at`; it should say `active` instead.
- Milestone 3's check-in screen for instructors must show only what check-in needs, never date of birth, notes or log entries.
