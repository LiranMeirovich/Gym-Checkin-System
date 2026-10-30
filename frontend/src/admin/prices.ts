// What the Prices screen needs: Hebrew names, and shekel text to and from
// whole agorot. Money never goes through a float: 19.99 × 100 isn't 1999 in
// floating point, so the text is split into its digits instead.
import type { Schemas } from "./backend/client";

export type Plan = Schemas["Plan"];
export type AgeGroup = Schemas["AgeGroup"];

export const PLAN_NAMES: Record<Plan, string> = {
  monthly: "חודשי",
  tri_monthly: "שלושה חודשים",
  single_entry: "כניסה בודדת",
};

export const AGE_GROUP_NAMES: Record<AgeGroup, string> = {
  adult: "מבוגר",
  under_18: "עד גיל 18",
};

export const PLANS: Plan[] = ["monthly", "tri_monthly", "single_entry"];
export const AGE_GROUPS: AgeGroup[] = ["adult", "under_18"];

/** The name the API's refusals and the form use for one price. */
export function priceField(plan: Plan, ageGroup: AgeGroup): string {
  return `${plan}.${ageGroup}`;
}

/** "250" → 25000, "19.9" → 1990, "19.99" → 1999. `null` if it isn't an
 * amount with at most two decimals; the limits are the server's. */
export function shekelsToAgorot(text: string): number | null {
  const match = /^([0-9]{1,9})(?:\.([0-9]{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
}

/** 25000 → "₪250", 1990 → "₪19.90". */
export function formatShekels(agorot: number): string {
  const shekels = Math.floor(agorot / 100);
  const rest = agorot % 100;
  return rest === 0
    ? `₪${shekels}`
    : `₪${shekels}.${String(rest).padStart(2, "0")}`;
}

/** "2026-11" → "11/2026". */
export function formatMonth(month: string): string {
  const [year, number] = month.split("-");
  return `${number}/${year}`;
}
