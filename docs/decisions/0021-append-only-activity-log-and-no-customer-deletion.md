# 0021. An append-only activity log of staff changes, and customers are never deleted

- Status: Accepted
- Date: 2026-10-26

## Context
The design doc says every staff change is recorded (who, what, when, before and after) so the manager can see what instructors did. That needs a table, one way for code to write to it, and answers to: what counts as a change, who the actor is before anyone can log in, and how strongly "read-only" is enforced. The design doc also had a full customer delete on request (`customers.delete`) that removed personal data, which would have meant scrubbing those values out of the log too.

The developer was advised that Israeli law allows keeping this kind of record, and the gym may need the history later, for example for its insurer.

## Options
- **What is logged:** data changes only / also logins and lockouts / every PIN attempt. `staff_sessions` already keeps every login.
- **Read-only:** only the core module writes, and it can only add rows / also SQLite triggers that refuse UPDATE and DELETE. Triggers rule out scrubbing a deleted customer's data from the log.
- **Actor at first-run setup:** the new manager is their own actor (`staff_user_id` NOT NULL) / a nullable actor meaning "system".
- **Customer removal:** archive and a separate full delete / archive only.

## Decision
- **One table, `activity_log`** (id, staff_user_id, action, target_type, target_id, before_json, after_json, at), written only through `app/core/activity_log.record()`, in the same transaction as the change. Actions (`staff.change_role`, `settings.update`, …) are a StrEnum in code with no CHECK in the database, so new ones need no migration. Their names are never renamed.
- **Only changes are logged**, not logins or lockouts.
- **The core function that makes a change records it**, taking the acting staff member as `by=`, so no route can make a change without its entry. A change that changes nothing writes no entry. Before/after hold only the fields that changed; a settings save is one entry with each changed setting's value in effect before (the default, if no row was stored) and after. PINs, hashes and tokens are never written (a PIN reset logs only that it happened).
- **Append-only, enforced twice:** the module offers no way to change or delete an entry, and two triggers make the database refuse UPDATE and DELETE.
- **The first manager is their own actor** at first-run setup; every entry has a real staff member.
- **Customers are never deleted**, only archived. `customers.delete` is removed, and archiving is the only way to remove a customer. Their data and log history stay.

## Consequences
- The log is trustworthy as evidence: not even a bug or a hand-written query can change it.
- A migration that rebuilds `activity_log` (batch mode) drops its triggers and must create them again; a test checks they exist at head.
- The log will hold personal data (staff names now, email addresses from settings, later customer fields) indefinitely. It's protected like the rest of the database (SQLCipher in milestone 6).
- A customer who asks to have their data removed can't have it removed in the app. The legal basis is the advice above; confirm it with the manager before launch.
- Old entries keep the before/after shape they were written with, so the log screen (milestone 4) must cope with older shapes.
- Every later feature adds its actions to `Action` and calls `record()` from its core functions; viewing a health form (milestone 3) is recorded the same way.
