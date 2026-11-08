// Permission checks for the screens: which menus, buttons and forms the
// logged-in staff member is offered.
//
// The server sends the role's named permissions with the session, so the
// one map stays ROLE_PERMISSIONS on the server (app/core/permissions.py):
// moving an action between roles needs no change here. Hiding something is
// never the protection: every route checks its own permission on the
// server (decision 0018). This only keeps a screen from offering what the
// server would refuse.
import type { Schemas } from "./backend/client";
import type { Session } from "./session";

export type Permission = Schemas["Permission"];

/** Whether the logged-in staff member's role has ``permission``. */
export function can(session: Session, permission: Permission): boolean {
  return session.permissions.includes(permission);
}
