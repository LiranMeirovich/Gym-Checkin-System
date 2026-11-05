// Plan names, prices and months as the customer pages show them. The admin
// build has its own copy (src/admin/prices.ts): the two builds never import
// from each other.
import type { Schemas } from "./backend/client";

export type Plan = Schemas["Plan"];

export const PLAN_NAMES: Record<Plan, string> = {
  monthly: "חודשי",
  tri_monthly: "שלושה חודשים",
  single_entry: "כניסה בודדת",
};

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

/** "2026-12" → "31/12/2026": the month's last day. */
export function lastDayOf(month: string): string {
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5, 7));
  // Day 0 of the next month is this month's last day.
  const day = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return `${day}/${String(number).padStart(2, "0")}/${year}`;
}

/** A timestamp from the API as the time in Israel, "14:05". */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("he-IL", {
    timeZone: "Asia/Jerusalem",
    hour: "2-digit",
    minute: "2-digit",
  });
}
