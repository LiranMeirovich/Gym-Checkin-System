// The page the wall QR opens. A phone that isn't linked gets the link
// form (its phone number and the code from the desk). A linked phone with
// no valid health form gets the form first (decision 0004); one whose
// form needs a doctor's note is sent to the desk. Checking in from here
// comes in feature 3 (decision 0028).
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { HealthForm } from "./HealthForm";

type Me = Schemas["Me"];

const ME_KEY = ["me"] as const;

/** Whose phone this is, or null when it isn't linked (a 401). */
async function fetchMe(): Promise<Me | null> {
  const { data, response } = await api.GET("/api/me");
  if (data) return data;
  if (response.status === 401) return null;
  throw new Error(`GET /api/me failed: ${response.status}`);
}

export function CheckIn() {
  const {
    data: me,
    isPending,
    isError,
  } = useQuery({
    queryKey: ME_KEY,
    queryFn: fetchMe,
  });

  if (isPending) return null;
  if (isError) return <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>;
  if (!me) return <LinkForm />;
  return <Linked me={me} />;
}

function day(iso: string): string {
  const [year, month, date] = iso.split("-");
  return `${date}/${month}/${year}`;
}

function Linked({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const form = me.health_form;

  if (form.state === "missing") {
    return (
      <HealthForm
        onSigned={(status) =>
          queryClient.setQueryData<Me>(ME_KEY, { ...me, health_form: status })
        }
      />
    );
  }
  if (form.state === "needs_doctor_note") {
    return (
      <>
        <h1>שלום, {me.first_name}</h1>
        <p role="alert">
          הצהרת הבריאות התקבלה. מכיוון שסימנת &quot;כן&quot; באחת השאלות, יש
          להביא לדלפק אישור רפואי מרופא לפני האימון.
        </p>
      </>
    );
  }
  return (
    <>
      <h1>שלום, {me.first_name}</h1>
      <p>הטלפון מקושר.</p>
      {form.valid_until && (
        <p>
          הצהרת הבריאות בתוקף עד <bdi>{day(form.valid_until)}</bdi>.
        </p>
      )}
    </>
  );
}

function LinkForm() {
  const queryClient = useQueryClient();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setMessage(null);
    try {
      const { data, response } = await api.POST("/api/link", {
        body: { phone, code },
      });
      if (data) {
        queryClient.setQueryData(ME_KEY, data);
        return;
      }
      if (response.status !== 400) {
        // Not a refusal (a 403 or a server error): asking for a new code
        // wouldn't help.
        setMessage("משהו השתבש. נסו שוב בעוד רגע.");
        return;
      }
      // One message for every refusal: the server never says which part
      // was wrong.
      setMessage(
        "מספר הטלפון או הקוד לא נכונים, או שהקוד כבר לא בתוקף. אפשר לבקש קוד חדש בדלפק.",
      );
    } catch {
      setMessage("אין חיבור לשרת. נסו שוב.");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <h1>קישור הטלפון</h1>
      <p>
        בפעם הראשונה צריך לקשר את הטלפון. בקשו קוד בדלפק והזינו אותו כאן עם מספר
        הטלפון שלכם.
      </p>
      <form onSubmit={submit}>
        {message && <p role="alert">{message}</p>}
        <p>
          <label htmlFor="phone">מספר טלפון</label>{" "}
          <input
            id="phone"
            type="tel"
            dir="ltr"
            autoComplete="tel"
            value={phone}
            maxLength={50}
            onChange={(event) => setPhone(event.target.value)}
            required
          />
        </p>
        <p>
          <label htmlFor="code">קוד מהדלפק</label>{" "}
          <input
            id="code"
            dir="ltr"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            maxLength={20}
            onChange={(event) => setCode(event.target.value)}
            required
          />
        </p>
        <p>
          <button type="submit" disabled={sending}>
            קישור
          </button>
        </p>
      </form>
    </>
  );
}
