// What the customer screens share: display formats, the Hebrew text for
// the API's error codes, and which buttons a role sees.
//
// Hiding a button is never the protection: every customer route checks its
// own permission on the server (decision 0023). This only keeps the
// screen from offering what the server would refuse.
import type { Schemas } from "./backend/client";
import type { Session } from "./session";

export type Customer = Schemas["CustomerDetails"];
// The fields a 400 can name. (The generated type of `errors` is keyed by
// any string, so the field names come from the request shape.)
export type CustomerField = keyof Schemas["NewCustomer"];

// The list has its own key under "customers", so refreshing it after a
// save doesn't also refetch the customer the save just answered with.
export const CUSTOMER_LIST_KEY = ["customers", "list"] as const;

export function customerKey(id: number) {
  return ["customers", id] as const;
}

// Shown next to the field. Each field has one rule, so one message each.
export const FIELD_ERRORS: Record<CustomerField, string> = {
  first_name: "שם פרטי: 1 עד 50 תווים",
  last_name: "שם משפחה: 1 עד 50 תווים",
  phone: "מספר טלפון ישראלי, למשל 050-1234567",
  date_of_birth: "תאריך לידה: לא בעתיד ולא לפני יותר מ-120 שנה",
  notes: "הערות: עד 256 תווים",
};

export const NOTES_MAX_LENGTH = 256;

/** The manager-only customer actions: changing a date of birth
 * (`customers.edit_birth_date`) and deactivating (`customers.archive`). */
export function isManager(session: Session): boolean {
  return session.staff.role === "manager";
}

/** "+972501234567" → "050-123-4567", "+97231234567" → "03-123-4567". */
export function formatPhone(stored: string): string {
  const local = "0" + stored.replace(/^\+972/, "");
  // 05x and 07x numbers have a three-digit prefix, landlines two.
  const prefix = local.length === 10 ? 3 : 2;
  const rest = local.slice(prefix);
  return `${local.slice(0, prefix)}-${rest.slice(0, 3)}-${rest.slice(3)}`;
}

/** "2001-05-17" → "17.5.2001", without going through a timezone. */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.slice(0, 10).split("-").map(Number);
  return `${day}.${month}.${year}`;
}
