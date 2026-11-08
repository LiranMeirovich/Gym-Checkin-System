# 0038. React checks named permissions sent with the session

- Status: Accepted
- Date: 2026-11-08

## Context
Milestone 4's first feature (decision 0037) hides the screens and buttons a role can't use. The server already checks a named permission on every route, mapped to roles in one place (`ROLE_PERMISSIONS`, decision 0018). Until now React asked only "is this the manager?" (`isManager()` in `roles.ts`), so it kept its own idea of which actions are manager-only. The permission split is still the design doc's proposal and the manager may move actions between roles before launch.

The same feature built the activity log screen, which raised a few smaller choices: how to page an append-only log, where the staff filter's list comes from before the Staff screen exists, and whether reading the log is itself logged.

## Options
- **Role helpers in React**: `roles.ts` hard-codes which actions are manager-only. Simple, no API change, but a second permission map that drifts from the server's whenever the split changes.
- **Permissions in the session answer**: the server sends the role's permission names with the session, and React checks those. One map stays the source of truth; it changes the session route contract (staff auth).
- Paging: offset pages, or keyset paging by id (`before_id`).
- Staff filter: send the staff names inside the log answer, or build feature 2's `GET /api/staff` now.

## Decision
- **The session answer carries `permissions`**: login, `GET /api/session` and first-run setup all return the role's permission names (`permissions_for()` in `app/core/permissions.py`). React checks them with `can(session, "<permission>")` in `roles.ts`; `isManager()` is gone, and every check uses the permission its route checks. `AppHeader`'s screens can name a permission and are listed only for roles that have it. Hiding is still never the protection: every route checks on the server.
- **A test keeps the manager-only routes honest**: `tests/test_admin_manager_only_routes.py` lists every manager-only route by hand, checks an instructor gets a 403 from each, and compares the list with the permissions the routes actually declare (`require_permission()` tags its check with its permission for this).
- **The activity log pages by id** (`before_id`, 50 a page, newest first), so entries added while the manager reads don't shift the pages.
- **`GET /api/staff` is built now** (manager only, `staff.manage`) for the log's staff filter; feature 2's Staff screen builds on it.
- **Reading the log isn't logged**: it holds no form contents or secrets, and decision 0021 logs only the sensitive reads the design doc names.
- **Filter rules live in core**: a target id needs a target type, and dates must be within 2000–2999; anything else is a 400 `invalid_filter`. The target filter is exact.

## Consequences
- Moving an action between roles is still a one-line change in `ROLE_PERMISSIONS`; React follows without a change.
- A role change reaches React only at the next `/api/session` fetch (reload or login). The server applies it from the next request, so the worst case is a button the server refuses.
- Every new manager-only route must be added to `MANAGER_ONLY`; the test fails until it is.
- The completeness test reads FastAPI's included routers (`original_router`), as `test_apps.py` does; a FastAPI change there breaks both tests loudly.
- A customer's full history (plan choices, check-ins, forms) doesn't show under a customer target filter; that needs a `customer_id` column or a JSON search later.
