// The lock screen: tap your name, enter your PIN (design doc: "Staff login
// and lock screen").
//
// Loading it ends this browser's session on the server (GET
// /api/lock-screen), however the browser got here: Lock, the auto-lock
// timer, Back, a typed address. A lock screen that looks locked is locked.
import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router";
import { api, type Schemas } from "../backend/client";
import { useForgetSession, useStartSession } from "../session";

type StaffName = Schemas["StaffName"];

const REFUSALS: Record<Schemas["LoginRefused"]["error"], string> = {
  wrong_pin: "קוד שגוי",
  locked: "יותר מדי ניסיונות שגויים.",
  no_such_staff: "המשתמש לא נמצא. בחרו שם מהרשימה.",
};
const NO_CONNECTION = "אין חיבור לשרת. נסו שוב.";

async function fetchLockScreen() {
  const { data, response } = await api.GET("/api/lock-screen");
  if (!data) throw new Error(`GET /api/lock-screen failed: ${response.status}`);
  return data;
}

export function LockScreen() {
  const forgetSession = useForgetSession();
  const { data, isPending, isError } = useQuery({
    queryKey: ["lock-screen"],
    queryFn: fetchLockScreen,
    // Fetched fresh on every visit, and never in the background: each
    // fetch ends whatever session this browser has, including one that
    // was just started from this screen.
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const [chosen, setChosen] = useState<StaffName | null>(null);

  // The server has ended the session; drop what this page knew of it.
  useEffect(() => forgetSession(), [forgetSession]);

  if (isPending) return null;
  if (isError) return <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>;
  if (data.setup_needed) return <Navigate to="/setup" replace />;

  return (
    <main>
      <h1>מי נכנס/ת?</h1>
      <nav aria-label="צוות">
        <ul>
          {data.staff.map((person) => (
            <li key={person.id}>
              <button
                type="button"
                aria-pressed={chosen?.id === person.id}
                onClick={() => setChosen(person)}
              >
                {person.display_name}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      {chosen && <PinForm key={chosen.id} staff={chosen} />}
    </main>
  );
}

function PinForm({ staff }: { staff: StaffName }) {
  const navigate = useNavigate();
  const startSession = useStartSession();
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    try {
      const { data, error } = await api.POST("/api/login", {
        body: { staff_id: staff.id, pin },
      });
      if (data) {
        startSession(data);
        navigate("/", { replace: true });
        return;
      }
      if (error && "error" in error) {
        const message = REFUSALS[error.error];
        setError(
          error.locked_until
            ? `${message} אפשר לנסות שוב בשעה ${wallClockTime(error.locked_until)}.`
            : message,
        );
      } else {
        setError(REFUSALS.wrong_pin);
      }
    } catch {
      // The request never got an answer (server down, network error).
      setError(NO_CONNECTION);
    } finally {
      setSending(false);
      setPin("");
    }
  }

  const fieldId = `pin-${staff.id}`;
  return (
    <form onSubmit={submit} autoComplete="off">
      {error && <p role="alert">{error}</p>}
      <p>
        <label htmlFor={fieldId}>הקוד של {staff.display_name}</label>{" "}
        <input
          id={fieldId}
          type="password"
          inputMode="numeric"
          pattern="[0-9]{6,12}"
          required
          autoFocus
          value={pin}
          onChange={(event) => setPin(event.target.value)}
        />
      </p>
      <p>
        <button type="submit" disabled={sending}>
          כניסה
        </button>
      </p>
    </form>
  );
}

/** "HH:MM" of a timestamp the server already gave in the gym's time zone
 * (with its offset). Read from the text, so the browser's own time zone
 * can't shift it. */
function wallClockTime(isoWithOffset: string): string {
  return isoWithOffset.slice(11, 16);
}
