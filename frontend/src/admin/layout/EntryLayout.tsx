// The screens before anyone is logged in, the lock screen and first-run
// setup: the gym's logo over one centred column.
import type { ReactNode } from "react";
import { Brand } from "../../shared/Brand";
import { useBranding } from "../branding";
import styles from "./EntryLayout.module.css";

export function EntryLayout({ children }: { children: ReactNode }) {
  const branding = useBranding();
  return (
    <main className={styles.screen}>
      <div className={styles.brand}>
        <Brand branding={branding} size="hero" />
      </div>
      <div className={styles.column}>{children}</div>
    </main>
  );
}
