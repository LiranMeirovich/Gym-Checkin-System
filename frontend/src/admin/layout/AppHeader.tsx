// The top bar of every logged-in staff screen: the gym, the screens the
// role can use, and who is logged in with Lock. A screen with a
// `permission` is listed only for roles that have it; the server refuses
// the screen's routes to the others anyway.
import { NavLink } from "react-router";
import { Brand } from "../../shared/Brand";
import { useBranding } from "../branding";
import { can, type Permission } from "../roles";
import { ROLE_NAMES, type Session } from "../session";
import styles from "./AppHeader.module.css";

type Screen = {
  to: string;
  label: string;
  end: boolean;
  permission?: Permission;
};

const SCREENS: Screen[] = [
  { to: "/", label: "ראשי", end: true },
  { to: "/customers", label: "לקוחות", end: false },
  { to: "/prices", label: "מחירון", end: true },
  { to: "/staff", label: "צוות", end: true, permission: "staff.manage" },
  {
    to: "/activity-log",
    label: "יומן פעולות",
    end: true,
    permission: "activity_log.view",
  },
  { to: "/settings", label: "הגדרות", end: true, permission: "settings.edit" },
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
        <NavLink to="/" className={styles.home}>
          <Brand branding={branding} size="header" />
        </NavLink>
        <nav aria-label="מסכים" className={styles.nav}>
          {SCREENS.filter(
            (screen) => !screen.permission || can(session, screen.permission),
          ).map((screen) => (
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
