// What the Prices screen needs: the plans in order, and shekel text to and
// from whole agorot. Money never goes through a float: 19.99 × 100 isn't 1999 in
// floating point, so the text is split into its digits instead. Plan names
// and the money and month formats are shared with the customer app
// (src/shared/plans.ts).
import type { Plan } from "../shared/plans";

export {
  PLAN_NAMES,
  formatMonth,
  formatShekels,
  type Plan,
} from "../shared/plans";

export const PLANS: Plan[] = ["monthly", "tri_monthly", "single_entry"];

/** "250" → 25000, "19.9" → 1990, "19.99" → 1999. `null` if it isn't an
 * amount with at most two decimals; the limits are the server's. */
export function shekelsToAgorot(text: string): number | null {
  const match = /^([0-9]{1,9})(?:\.([0-9]{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
}
