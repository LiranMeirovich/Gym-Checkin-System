// How the activity log reads in Hebrew: names for actions, targets and the
// fields in before/after, and how each value is shown.
//
// An entry keeps the shape it was written with (decision 0021), so nothing
// here may assume one: an action, target or field without a Hebrew name
// shows its stored name, and a value of an unexpected type is shown as
// text. New actions (app/core/activity_log.py `Action`) should get a name
// here, but a missing one never breaks the screen.
import type { Schemas } from "./backend/client";
import { formatDate, formatPhone } from "./customers";
import {
  PLAN_NAMES,
  formatMonth,
  formatShekels,
  type Plan,
} from "../shared/plans";
import { ROLE_NAMES } from "./session";

export type LogEntry = Schemas["ActivityLogItem"];
export type LogPage = Schemas["ActivityLogPage"];

export const ACTION_NAMES: Record<string, string> = {
  "staff.create": "איש צוות נוסף",
  "staff.reset_pin": "קוד אישי אופס",
  "staff.change_role": "תפקיד שונה",
  "staff.deactivate": "איש צוות הושבת",
  "staff.reactivate": "איש צוות הופעל מחדש",
  "settings.update": "הגדרות עודכנו",
  "customer.create": "לקוח נוסף",
  "customer.edit": "פרטי לקוח עודכנו",
  "customer.change_date_of_birth": "תאריך לידה שונה",
  "customer.deactivate": "לקוח הושבת",
  "customer.reactivate": "לקוח הופעל מחדש",
  "price.add": "מחיר נקבע",
  "plan.choose": "מסלול נבחר",
  "plan.correct": "מסלול תוקן",
  "plan.clear": "מסלול בוטל",
  "phone.issue_code": "קוד חיבור טלפון הונפק",
  "phone.unlink": "טלפון נותק",
  "health_form.open": "הצהרת בריאות נפתחה",
  "health_form.add_doctor_note": "אישור רפואי נוסף",
  "health_form.fill_in": "הצהרת בריאות מולאה בעמדה",
  "doctor_note.open": "אישור רפואי נפתח",
  "checkin.manual": "כניסה ידנית",
};

/** The targets the filter offers, in the order it lists them. */
export const TARGET_NAMES: Record<string, string> = {
  customer: "לקוח",
  staff_user: "איש צוות",
  plan_choice: "בחירת מסלול",
  checkin: "כניסה",
  price: "מחיר",
  health_form: "הצהרת בריאות",
  doctor_note: "אישור רפואי",
  device_session: "טלפון מחובר",
  settings: "הגדרות",
};

const FIELD_NAMES: Record<string, string> = {
  // Customers
  first_name: "שם פרטי",
  last_name: "שם משפחה",
  phone: "טלפון",
  date_of_birth: "תאריך לידה",
  notes: "הערות",
  active: "פעיל",
  // Staff
  display_name: "שם",
  role: "תפקיד",
  // Prices and plans
  plan: "מסלול",
  amount_agorot: "מחיר",
  unit_price_agorot: "מחיר",
  valid_from_month: "בתוקף מ־",
  start_month: "מחודש",
  end_month: "עד חודש",
  // Written before one price per plan (decision 0036).
  age_group: "קבוצת גיל",
  // Settings
  gym_name: "שם המכון",
  manager_email: "אימייל המנהל",
  report_recipients: "מקבלי הדוח",
  lock_screen_minutes: "נעילה אחרי (דקות, מנהל)",
  instructor_lock_screen_minutes: "נעילה אחרי (דקות, מדריך)",
  // Links to other rows
  id: "מזהה",
  customer_id: "לקוח",
  plan_choice_id: "בחירת מסלול",
  link_code_id: "קוד חיבור",
  doctor_note_id: "אישור רפואי",
  revoked: "נותק",
};

const AGE_GROUPS: Record<string, string> = {
  adult: "מבוגר",
  under_18: "מתחת ל־18",
};

export function actionName(action: string): string {
  return ACTION_NAMES[action] ?? action;
}

export function targetName(targetType: string): string {
  return TARGET_NAMES[targetType] ?? targetType;
}

export function fieldName(field: string): string {
  return FIELD_NAMES[field] ?? field;
}

/** A before/after value as text. `null` is "—"; a value whose type isn't
 * the one this field usually has is shown as written. */
export function formatValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "כן" : "לא";
  if (typeof value === "number" && field.endsWith("_agorot")) {
    return formatShekels(value);
  }
  if (typeof value === "string") {
    if (field === "plan" && value in PLAN_NAMES) {
      return PLAN_NAMES[value as Plan];
    }
    if (field === "role" && value in ROLE_NAMES) {
      return ROLE_NAMES[value as keyof typeof ROLE_NAMES];
    }
    if (field === "age_group") return AGE_GROUPS[value] ?? value;
    if (field === "phone") return formatPhone(value);
    if (field === "date_of_birth" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return formatDate(value);
    }
    if (field.endsWith("_month") && /^\d{4}-\d{2}$/.test(value)) {
      return formatMonth(value);
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.length === 0
      ? "—"
      : value.map((item) => formatValue(field, item)).join(", ");
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** Values that read left to right (phone numbers, emails, ids, amounts),
 * so the screen wraps them in an LTR span inside the RTL table. */
export function isLtr(field: string): boolean {
  return (
    field === "phone" ||
    field.endsWith("_agorot") ||
    field.endsWith("email") ||
    field === "report_recipients" ||
    field === "id" ||
    field.endsWith("_id")
  );
}

export type Change = {
  field: string;
  before?: unknown;
  after?: unknown;
  // Which side the entry has: a creation has only "after", a removal only
  // "before".
  hasBefore: boolean;
  hasAfter: boolean;
};

const FIELD_ORDER = Object.keys(FIELD_NAMES);

/** Where a field goes in the list: in FIELD_NAMES' order (the server
 * writes the keys sorted by name), fields without a name last. */
function rank(field: string): number {
  const index = FIELD_ORDER.indexOf(field);
  return index === -1 ? FIELD_ORDER.length : index;
}

/** Every field in before or after, in a steady order, paired up. */
export function changesOf(entry: LogEntry): Change[] {
  const before = entry.before ?? {};
  const after = entry.after ?? {};
  const fields = [
    ...new Set([...Object.keys(before), ...Object.keys(after)]),
  ].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  return fields.map((field) => ({
    field,
    before: before[field],
    after: after[field],
    hasBefore: entry.before !== null && field in before,
    hasAfter: entry.after !== null && field in after,
  }));
}
