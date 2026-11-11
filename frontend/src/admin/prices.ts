// What the Prices screen needs: the plans in order, and shekel text to and
// from whole agorot. Money never goes through a float: 19.99 × 100 isn't 1999 in
// floating point, so the text is split into its digits instead. Plan names
// and the money and month formats are shared with the customer app
// (src/shared/plans.ts).
import { PLAN_NAMES, type Plan } from "../shared/plans";

export {
  PLAN_NAMES,
  formatMonth,
  formatShekels,
  type Plan,
} from "../shared/plans";

export const PLANS: Plan[] = [
  "monthly",
  "tri_monthly",
  "single_entry",
  "punch_card",
];

/** A row of the price table: the plan's name, with the card's size (from
 * the server). */
export function priceRowName(plan: Plan, cardEntries: number): string {
  return plan === "punch_card"
    ? `${PLAN_NAMES.punch_card} (${cardEntries} כניסות)`
    : PLAN_NAMES[plan];
}

/** "250" → 25000, "19.9" → 1990, "19.99" → 1999. `null` if it isn't an
 * amount with at most two decimals; the limits are the server's. */
export function shekelsToAgorot(text: string): number | null {
  const match = /^([0-9]{1,9})(?:\.([0-9]{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
}
