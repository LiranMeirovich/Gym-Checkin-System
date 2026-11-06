// A short status in colour: the health form, the month's plan, a check-in.
// The words carry the meaning; the colour only repeats it.
import type { ReactNode } from "react";
import styles from "./Status.module.css";

/** ok: allowed / in force. stop: blocks check-in. warn: needs attention. */
export type Tone = "ok" | "stop" | "warn";

export function StatusBadge({
  tone,
  children,
}: {
  tone: Tone;
  children: ReactNode;
}) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
