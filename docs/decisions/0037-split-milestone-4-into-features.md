# 0037. Split milestone 4 into five features, activity log first

- Status: Accepted
- Date: 2026-11-08

## Context
The design doc's milestone 4 (Admin screens) lists the dashboard with live check-ins and expiring health forms, customer list search, the customer page, prices, settings, staff accounts, the lock screen and role-filtered menus. The styling pass was pulled forward into milestone 3 (decision 0034). The lock screen, the customer page (phones, health form, plan and its history) and the prices screen already exist from milestones 1–3. The core functions for staff accounts (`app/core/staff.py`) and settings (`app/core/gym_settings.py`) exist too, but they have no routes or screens. The roles table also gives the manager an activity log view (`activity_log.view`), which the milestone list doesn't name. As with milestones 2 and 3 (decisions 0022, 0028), one feature = one branch = one PR = one session.

A milestone 3 follow-up was considered too: a "customer mode" for the health form on the desk PC. The customer fills in that form inside a logged-in staff session, so they could leave it and browse the admin app, and the manager's 5-minute auto-lock could wipe a slow customer's form.

## Options
- **Activity log screen**: leave it out of milestone 4 (not in the milestone list), or build it now. The developer wants it soon: it is how the manager sees what instructors did.
- **Customer mode at the desk PC**: (a) build it, with the server limiting the session to one customer's form, keeping it alive, and asking for a staff PIN to leave; (b) only lock the PC after signing or cancelling; (c) don't build it, and have staff stay with the customer. Option (a) touches staff sessions and the schema for a rare case: most customers fill in the form on their own phone.
- **How a live dashboard refresh avoids counting as activity for the auto-lock**: decide now, or in the dashboard feature's plan, where the details are known.

## Decision
Build milestone 4 as five features, in this order:

1. **Activity log screen and role-filtered menus**: a manager-only, paged activity log, filtered by staff member, date and target, that copes with older before/after shapes. `AppHeader` hides the screens a role can't use (helpers in `frontend/src/admin/roles.ts`). One test loops over every manager-only admin route and checks that an instructor is refused; each later feature adds its routes to it.
2. **Staff accounts**: a manager-only Staff screen with routes over the existing core functions: list, add, reset a PIN, change a role, deactivate and reactivate.
3. **Settings screen**: manager-only. Gym name, manager email, report recipients and the two lock times, through `load_gym_settings_for_editing()` and `update_gym_settings()`.
4. **Customer list search and filters**: search by name or phone and a "checked in recently" filter, as server-side queries, plus a short check-in history on the customer page.
5. **Dashboard**: today's check-ins, refreshed live; health forms that need a doctor's note and forms expiring in the next 30 days; the latest sign-ups (newest `created_at`, decision 0035). How background refreshes skip the auto-lock timer is decided in this feature's plan. The same change lets the customer page's phone list refresh while a link code is on screen.

**No customer mode.** Staff stay with the customer while they fill in the form on the desk PC. A separate tablet for customers may come later, and with it its own screen, as a feature of its own.

## Consequences
- Each feature starts in a new session with `/start-feature <feature>`. CLAUDE.md's Project status tracks which one is next.
- Features 1 and 2 touch staff auth (protected area); feature 5 touches staff sessions (the auto-lock).
- The desk-PC risks stay, covered by staff being present: a customer left alone at the PC could leave the form for the admin app, and a slow customer can lose their form to the manager's 5-minute lock. Instructors (60 minutes) are much less affected. Before launch, the gym's staff are told to stay with the customer.
- Left out of milestone 4: the dashboard's report and backup cards (milestones 5 and 6), staff changing their own PIN, punch cards and the customer tablet screen.
