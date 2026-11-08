// The page the wall QR opens. A phone that isn't linked gets the link
// form (its phone number and the code from the desk), or a new customer
// signs up on it (SignUpForm, decision 0035). A linked phone with
// no valid health form gets the form first (decision 0004); one whose
// form needs a doctor's note is sent to the desk. Otherwise the phone
// checks in straight away (CheckInStep), right after linking or signing
// the form too.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { CheckInStep } from "./CheckInStep";
import { HealthForm } from "./HealthForm";
import { SignUpForm } from "./SignUpForm";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
} from "../../shared/NoConnection";
import styles from "./Phone.module.css";

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
  if (isError) return <NoConnection />;
  if (!me) return <NotLinked />;
  return <Linked me={me} />;
}

function Linked({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const form = me.health_form;
  const setForm = (status: Me["health_form"]) =>
    queryClient.setQueryData<Me>(ME_KEY, { ...me, health_form: status });

  if (form.state === "missing") {
    return <HealthForm onSigned={setForm} />;
  }
  if (form.state === "needs_doctor_note") {
    return (
      <>
        <h1 className={styles.heading}>שלום, {me.first_name}</h1>
        <p role="alert">
          הצהרת הבריאות התקבלה. מכיוון שסימנת &quot;כן&quot; באחת השאלות, יש
          להביא לדלפק אישור רפואי מרופא לפני האימון.
        </p>
      </>
    );
  }
  return (
    <CheckInStep
      firstName={me.first_name}
      formValidUntil={form.valid_until}
      onHealthFormRequired={setForm}
      onNotLinked={() => queryClient.setQueryData(ME_KEY, null)}
    />
  );
}

/** Linking with a code from the desk, or signing up as a new customer.
 * Either way the answer is the customer, and the page carries on as a
 * linked phone. */
function NotLinked() {
  const queryClient = useQueryClient();
  const [signingUp, setSigningUp] = useState(false);
  const linked = (me: Me) => queryClient.setQueryData(ME_KEY, me);

  if (signingUp) {
    return (
      <SignUpForm onSignedUp={linked} onHaveCode={() => setSigningUp(false)} />
    );
  }
  return <LinkForm onLinked={linked} onNew={() => setSigningUp(true)} />;
}

function LinkForm({
  onLinked,
  onNew,
}: {
  onLinked: (me: Me) => void;
  onNew: () => void;
}) {
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
        onLinked(data);
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
      setMessage(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <h1 className={styles.heading}>קישור הטלפון</h1>
      <p className={styles.lead}>
        בפעם הראשונה צריך לקשר את הטלפון. בקשו קוד בדלפק והזינו אותו כאן עם מספר
        הטלפון שלכם.
      </p>
      <form onSubmit={submit} className={styles.panel}>
        {message && <p role="alert">{message}</p>}
        <p className={styles.field}>
          <label htmlFor="phone">מספר טלפון</label>
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
        <p className={styles.field}>
          <label htmlFor="code">קוד מהדלפק</label>
          <input
            id="code"
            className={styles.code}
            dir="ltr"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            maxLength={20}
            onChange={(event) => setCode(event.target.value)}
            required
          />
        </p>
        <button type="submit" className={styles.wide} disabled={sending}>
          קישור
        </button>
      </form>
      <p className={styles.switch}>
        חדשים במכון?{" "}
        <button type="button" onClick={onNew}>
          הרשמה
        </button>
      </p>
    </>
  );
}
