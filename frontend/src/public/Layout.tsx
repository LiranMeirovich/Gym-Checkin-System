// Every phone page: the gym's logo at the top, one narrow column below.
// Mobile first; on a wider screen the column just stays narrow.
import type { ReactNode } from "react";
import { Brand } from "../shared/Brand";
import { useBranding } from "./branding";
import styles from "./Layout.module.css";

export function Layout({ children }: { children: ReactNode }) {
  const branding = useBranding();
  return (
    <div className={styles.screen}>
      <header className={styles.top}>
        <Brand branding={branding} size="header" />
      </header>
      <main className={styles.column}>{children}</main>
    </div>
  );
}
