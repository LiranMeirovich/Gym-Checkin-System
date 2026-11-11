// Plan names, money and months, as both apps show them. Shared code
// imports neither build's API types, so `Plan` is spelled out here; an API
// change that adds a plan fails the type-check of `PLAN_NAMES` wherever an
// app passes its own `Plan` in. A punch card's size and dates come from the
// server (decision 0043), never worked out here.

export type Plan = "monthly" | "tri_monthly" | "single_entry" | "punch_card";

// The report's Excel and PDF files use the same names, written in Python
// (app/core/report_files.py `PLAN_NAMES`): change both together.
export const PLAN_NAMES: Record<Plan, string> = {
  monthly: "חודשי",
  tri_monthly: "שלושה חודשים",
  single_entry: "כניסה בודדת",
  punch_card: "כרטיסייה",
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

/** After the card's last entry: it no longer counts, whatever its date. */
export const LAST_CARD_ENTRY = "זו הייתה הכניסה האחרונה בכרטיסייה";

/** "נותרו 12 כניסות", "נותרה כניסה אחת". */
export function entriesLeftText(count: number): string {
  return count === 1 ? "נותרה כניסה אחת" : `נותרו ${count} כניסות`;
}
