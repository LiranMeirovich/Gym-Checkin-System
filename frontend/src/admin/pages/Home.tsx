// Placeholder until the dashboard (milestone 4).
import { useSession } from "../session";

export function Home() {
  const { staff } = useSession();
  return (
    <>
      <h1>שלום, {staff.display_name}</h1>
      <p>לוח הבקרה יגיע בהמשך.</p>
    </>
  );
}
