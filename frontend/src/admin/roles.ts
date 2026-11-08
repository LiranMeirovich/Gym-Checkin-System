// Role checks for the screens: which buttons and forms a role is offered.
//
// Hiding something is never the protection: every route checks its own
// named permission on the server (decision 0018). This only keeps a screen
// from offering what the server would refuse. Milestone 4's role-filtered
// menus use these too.
import type { Session } from "./session";

/** The manager-only actions: changing a date of birth, deactivating a
 * customer, choosing and correcting plans, editing prices, the full
 * health form. */
export function isManager(session: Session): boolean {
  return session.staff.role === "manager";
}
