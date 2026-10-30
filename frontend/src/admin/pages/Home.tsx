// Placeholder until the dashboard (milestone 4).
import { Link } from "react-router";
import { useSession } from "../session";

export function Home() {
  const { staff } = useSession();
  return (
    <>
      <h1>שלום, {staff.display_name}</h1>
      <p>לוח הבקרה יגיע בהמשך.</p>
      <p>
        <Link to="/customers">לקוחות</Link> · <Link to="/prices">מחירון</Link>
      </p>
    </>
  );
}
