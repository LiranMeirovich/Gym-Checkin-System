// The top bar of every logged-in staff screen: the gym, the screens, and
// who is logged in with Lock. The role-filtered menus come in milestone 4;
// every screen here is open to both roles (the server checks anyway).
import { NavLink } from "react-router";
import { Brand } from "../../shared/Brand";
import { useBranding } from "../branding";
import { ROLE_NAMES, type Session } from "../session";
import styles from "./AppHeader.module.css";

const SCREENS = [
  { to: "/", label: "ראשי", end: true },
  { to: "/customers", label: "לקוחות", end: false },
  { to: "/prices", label: "מחירון", end: true },
];

export function AppHeader({
  session,
  onLock,
}: {
  session: Session;
  onLock: () => void;
}) {
  const branding = useBranding();
  return (
    <header className={styles.bar}>
      <div className={styles.inner}>
        <NavLink to="/" className={styles.home} aria-label="ראשי">
          <Brand branding={branding} size="header" />
        </NavLink>
        <nav aria-label="מסכים" className={styles.nav}>
          {SCREENS.map((screen) => (
            <NavLink
              key={screen.to}
              to={screen.to}
              end={screen.end}
              className={({ isActive }) =>
                isActive ? `${styles.link} ${styles.active}` : styles.link
              }
            >
              {screen.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.who}>
          <span className={styles.name}>{session.staff.display_name}</span>
          <span className={styles.role}>{ROLE_NAMES[session.staff.role]}</span>
          <button type="button" className={styles.lock} onClick={onLock}>
            נעילה
          </button>
        </div>
      </div>
    </header>
  );
}
