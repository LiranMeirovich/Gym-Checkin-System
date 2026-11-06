// The gym's logo, or its name when the install has no logo file (decision
// 0034). Each app fetches GET /api/branding through its own client and
// passes the answer in: shared code imports neither app.
import styles from "./Brand.module.css";

export type Branding = { gym_name: string | null; has_logo: boolean };

// Served by both apps from the install's git-ignored branding/ folder.
const LOGO_ADDRESS = "/branding/logo";

/** `size`: "header" in a top bar, "hero" at the top of a page. */
export function Brand({
  branding,
  size,
}: {
  branding: Branding | undefined;
  size: "header" | "hero";
}) {
  // While the answer is on its way, keep the space so nothing jumps.
  if (!branding) return <span className={styles[size]} aria-hidden="true" />;
  const name = branding.gym_name ?? "";
  if (branding.has_logo) {
    return (
      <span className={`${styles.brand} ${styles[size]}`}>
        <img className={styles.logo} src={LOGO_ADDRESS} alt={name} />
        {size === "header" && name && (
          <span className={styles.name}>{name}</span>
        )}
      </span>
    );
  }
  return (
    <span className={`${styles.brand} ${styles[size]}`}>
      <span className={styles.wordmark}>{name}</span>
    </span>
  );
}
