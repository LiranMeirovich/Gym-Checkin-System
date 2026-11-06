// Placeholder until the dashboard (milestone 4): a greeting and the way
// into the two screens that exist.
import { Link } from "react-router";
import { useSession } from "../session";
import styles from "./Home.module.css";

export function Home() {
  const { staff } = useSession();
  return (
    <>
      <h1 className={styles.greeting}>שלום, {staff.display_name}</h1>
      <p className={styles.lead}>לוח הבקרה יגיע בהמשך.</p>
      <nav aria-label="מסכים" className={styles.doors}>
        <Link to="/customers" className={styles.door}>
          <span className={styles.doorName}>לקוחות</span>
          <span className={styles.doorText}>
            רשימת הלקוחות, כניסות, תוכניות, הצהרות בריאות וטלפונים
          </span>
        </Link>
        <Link to="/prices" className={styles.door}>
          <span className={styles.doorName}>מחירון</span>
          <span className={styles.doorText}>
            המחירים החודש, שינויים עתידיים והיסטוריה
          </span>
        </Link>
      </nav>
    </>
  );
}
