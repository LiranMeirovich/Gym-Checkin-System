// Plan names, money and months, as both apps show them. Shared code
// imports neither build's API types, so `Plan` is spelled out here; an API
// change that adds a plan fails the type-check of `PLAN_NAMES` wherever an
// app passes its own `Plan` in.

export type Plan = "monthly" | "tri_monthly" | "single_entry";

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
