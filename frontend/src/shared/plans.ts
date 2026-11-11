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

/** A punch card's `expires_on` ("2027-01-01", always a month's 1st) as
 * the month it's last valid in ("2026-12"). */
export function lastCardMonth(expiresOn: string): string {
  return addMonths(expiresOn.slice(0, 7), -1);
}

/** "נותרו 12 כניסות", "נותרה כניסה אחת". */
export function entriesLeftText(count: number): string {
  return count === 1 ? "נותרה כניסה אחת" : `נותרו ${count} כניסות`;
}
