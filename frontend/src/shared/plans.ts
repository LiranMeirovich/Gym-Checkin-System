// Plan names, money and months, as both apps show them. Shared code
// imports neither build's API types, so `Plan` is spelled out here; an API
// change that adds a plan fails the type-check of `PLAN_NAMES` wherever an
// app passes its own `Plan` in.

export type Plan = "monthly" | "tri_monthly" | "single_entry" | "punch_card";

export const PLAN_NAMES: Record<Plan, string> = {
  monthly: "חודשי",
  tri_monthly: "שלושה חודשים",
  single_entry: "כניסה בודדת",
  punch_card: "כרטיסייה",
};

// Entries on a punch card: the server's `CARD_ENTRIES`
// (app/core/models/punch_cards.py, decision 0042), a fixed number.
export const CARD_ENTRIES = 20;

/** 25000 → "₪250", 1990 → "₪19.90". Whole agorot, never a float. */
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

/** "2026-11" plus 1 → "2026-12". */
export function addMonths(month: string, count: number): string {
  const index = Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1;
  const total = index + count;
  const year = Math.floor(total / 12);
  return `${year}-${String((total % 12) + 1).padStart(2, "0")}`;
}

/** The last day a card bought in `month` ("2026-11") counts: the end of
 * the next month, as an ISO date ("2026-12-31"). Each app formats it its
 * own way. */
export function cardValidUntil(month: string): string {
  return lastDayOf(addMonths(month, 1));
}

/** A punch card's `expires_on` ("2027-01-01", the first day it no longer
 * counts) as its last valid day, an ISO date ("2026-12-31"). */
export function cardLastDay(expiresOn: string): string {
  return lastDayOf(addMonths(expiresOn.slice(0, 7), -1));
}

/** "2026-12" → "2026-12-31": the month's last day. */
function lastDayOf(month: string): string {
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5, 7));
  // Day 0 of the next month is this month's last day.
  const day = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return `${month}-${String(day).padStart(2, "0")}`;
}

/** "נותרו 12 כניסות", "נותרה כניסה אחת". */
export function entriesLeftText(count: number): string {
  return count === 1 ? "נותרה כניסה אחת" : `נותרו ${count} כניסות`;
}
