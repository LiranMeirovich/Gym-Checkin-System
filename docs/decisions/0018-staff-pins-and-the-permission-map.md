# 0018. Staff log in with Argon2id-hashed PINs; permissions live in one map

- Status: Accepted
- Date: 2026-10-25

## Context
Staff log in on the shared front-desk PC by tapping their name and typing a secret, and the app locks again after a few idle minutes. The design doc mostly says a PIN of at least 6 digits, but a few lines said "password" (left open in [0008](0008-split-milestone-1-into-features.md)). It requires PINs stored as bcrypt or argon2 hashes, a lockout after 5 wrong PINs, and permissions checked on the server by name, mapped to roles in one place. This feature had to settle the secret, the hashing library, the account rules and the shape of the permission map.

## Options
- **Secret:** a password (strong, slow to type at a busy desk, gets written on a sticky note) / a numeric PIN (fast, but a small space of values).
- **Hashing:** `bcrypt` (proven; 72-byte limit, CPU-hard only) / `argon2-cffi` (Argon2id, OWASP's first choice, memory-hard, built-in parameter upgrade check) / `pwdlib` (a wrapper over both; one more layer).
- **Name uniqueness:** none / unique across all rows / unique among active staff, ignoring case.
- **Permission map:** add permissions as each feature needs them / define them all now from the design doc's table.

## Decision
- **A PIN of 6–12 ASCII digits.** All-one-digit PINs (`000000`) and straight runs (`123456`, `987654`) are refused. "Password" in the design doc was loose wording and now says PIN. The rules apply when a PIN is set, not when it's checked, so a later rule change doesn't lock anyone out.
- **Argon2id through `argon2-cffi`**, with the library's default parameters. `app/core/pins.py` is the only module that touches it. A correct PIN whose hash used older parameters is re-hashed on the spot. A CHECK constraint lets only Argon2id hashes into `staff_users.pin_hash`.
- **Lockout:** the 5th wrong PIN in a row locks the account for 5 minutes and starts the count again. While locked or inactive, attempts are refused without checking the PIN and don't count. A manager's PIN reset lifts a lockout.
- **Names are unique among active staff, ignoring case** (a partial unique index), since the lock screen tells people apart by name. A deactivated member's name can be reused.
- **There's always an active manager:** the last one can't be demoted or deactivated.
- **All permissions are defined now** in `app/core/permissions.py`: 20 named `area.action` permissions and one read-only role map. The manager gets all of them; instructors get the desk work (see [0017](0017-instructors-never-choose-plans.md) for plans).

## Consequences
- A 6-digit PIN can be brute-forced offline from a copy of `gym.db`, Argon2 or not. The lockout only protects the lock screen; the real protection for the file is SQLCipher and disk encryption (milestone 6). Until then, treat any copy of `gym.db` as sensitive.
- Anyone at the desk can lock a colleague out for 5 minutes with wrong PINs. Acceptable for one front desk; the manager can lift it with a reset.
- The lockout counters are written in the request's transaction, so the login route must commit a failed login, not raise and roll it back.
- Each PIN check takes a noticeable fraction of a second and 64 MiB of memory on purpose.
- Moving to another hashing algorithm later needs a migration for the CHECK constraint, plus re-hashing at login.
- The role split is still the design doc's proposal; the manager confirms it later, and a change is one line in the map (and its test).
- Still open from 0008, for the next feature: whether the lock screen is built in milestone 1 or 4.
