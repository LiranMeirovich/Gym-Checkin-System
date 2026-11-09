# 0039. An owner role manages the managers; a PIN reset logs the member out

- Status: Accepted
- Date: 2026-11-09

## Context
Milestone 4's Staff screen (decision 0037) put the existing staff functions behind routes. Until then any manager could change any staff account, and the only guards were "always one active manager" (decision 0018) and, added early in this feature, "a manager can't demote or deactivate themselves". The developer wants the gym's main manager protected: a manager they add to help them must not be able to demote, deactivate or take over the main manager's account, while the main manager can still deactivate that helper. A second manager isn't expected yet, but may come.

The feature also settled what a PIN reset does to open sessions, and how the screen shows a lockout.

## Options
- **How to mark the main manager**: a third role, `owner` / an `is_owner` flag on a manager. A flag keeps two roles but adds a second way of deciding who may do what next to the permission map.
- **What a regular manager may do to accounts**: manage instructors only / manage everyone but the owner.
- **A PIN reset and open sessions**: leave them / end them.

## Decision
- **A third role, `owner`**, with every permission. Managers have every permission except the new `staff.manage_managers`. Code still checks named permissions; React follows the session's permission list.
- **Exactly one owner**, made only at first-run setup (`create_owner()`). A partial unique index allows at most one owner row; core refuses demoting or deactivating the owner, making anyone else the owner (the routes only accept `manager` or `instructor`), and anyone but the owner resetting the owner's PIN (409 `owner`). Existing databases make their oldest active manager the owner (migration `23b9f8717ccd`).
- **Only the owner manages managers**: adding one, promoting to or demoting from manager, resetting a manager's PIN, deactivating and reactivating one. A manager gets a 403. This is checked in `app.core.staff`, since it depends on whose account it is, not only on the route.
- **Anyone may reset their own PIN.**
- **Replaced**: decision 0018's "always an active manager" and the "can't demote or deactivate yourself" rule. Both can no longer happen: the owner is always active and has every permission, and a manager can't change managers' accounts, their own included.
- **A PIN reset ends every open session of that member**, except the resetting manager's own session when they reset their own PIN: a reset usually means the old PIN got out.
- **The staff list shows a lockout** (`locked_until`, only while it lasts), and a PIN reset lifts it.

## Consequences
- The owner's account can't be helped from the app: a forgotten owner PIN needs a command run on the PC itself, and there's no ownership transfer (the gym changing hands). Both are follow-ups.
- A regular manager can't fix a mistake on another manager's account; the owner has to.
- Moving an action between owner and manager stays a one-line change in `ROLE_PERMISSIONS`, but the account rules (whose account) live in `app.core.staff`.
- The owner locks after the managers' idle time (`lock_screen_minutes`).
