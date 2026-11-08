// What the customer screens share: display formats and the Hebrew text
// for the API's error codes. Which buttons a role sees is in roles.ts.
import type { Schemas } from "./backend/client";

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

// The customer's plan status. Under the customer's key, but a save that
// only writes the customer with setQueryData doesn't refresh it, so the
// saves that change it (a plan choice or correction, a check-in that
// chooses a plan) refresh it themselves.
export function planKey(id: number) {
  return ["customers", id, "plan"] as const;
}

// The customer's health form status (valid, needs a note, missing). Signing
// a form or adding a doctor's note answers with the new one.
export function healthFormKey(id: number) {
  return ["customers", id, "health-form"] as const;
}

// The manager's list of the customer's signed forms and their notes.
export function healthFormsKey(id: number) {
  return ["customers", id, "health-forms"] as const;
}

// The customer's linked phones. An unlink answers with the new list, which
// goes straight into the cache.
export function phonesKey(id: number) {
  return ["customers", id, "phones"] as const;
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

/** "2026-11-03T14:05:00+02:00" → "14:05". The server sends the gym's
 * local time, so this reads it as written, without a timezone. */
export function formatTime(isoDateTime: string): string {
  return isoDateTime.slice(11, 16);
}
