// Signing up on the phone (decision 0035): a new customer types their
// name, phone and date of birth. The server creates the customer and this
// phone's login (the gym_device cookie) in one go and answers like linking
// does, so the page carries on as a linked phone: the health form first.
//
// A number that is already a customer's, active or not, is refused: that
// customer links the phone at the desk instead.
import { useState, type FormEvent, type ReactNode } from "react";
import { api, type Schemas } from "../backend/client";
import { NO_CONNECTION_TRY_AGAIN } from "../../shared/NoConnection";
import { todayInIsrael } from "../times";
import styles from "./Phone.module.css";

type Details = Schemas["SignUpRequest"];
type SignUpField = keyof Details;

const EMPTY: Details = {
  first_name: "",
  last_name: "",
  phone: "",
  date_of_birth: "",
};

// The rules are app.core.customers'; these only say them to the customer.
// The example number is isolated and kept whole, or the RTL line splits it.
const FIELD_ERRORS: Record<SignUpField, ReactNode> = {
  first_name: "יש למלא שם פרטי, עד 50 תווים.",
  last_name: "יש למלא שם משפחה, עד 50 תווים.",
  phone: (
    <>
      יש להזין מספר טלפון ישראלי, למשל{" "}
      <bdi dir="ltr" className={styles.number}>
        050-1234567
      </bdi>
      .
    </>
  ),
  date_of_birth: "תאריך הלידה לא נראה נכון.",
};

export function SignUpForm({
  onSignedUp,
  onHaveCode,
}: {
  onSignedUp: (me: Schemas["Me"]) => void;
  onHaveCode: () => void;
}) {
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<SignUpField, ReactNode>>>(
    {},
  );
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setMessage(null);
    try {
      const { data, error, response } = await api.POST("/api/sign-up", {
        body: values,
      });
      if (data) {
        onSignedUp(data);
        return;
      }
      setErrors({});
      if (response.status === 400 && error && "errors" in error) {
        const fields = Object.keys(error.errors) as SignUpField[];
        setErrors(Object.fromEntries(fields.map((f) => [f, FIELD_ERRORS[f]])));
      } else if (response.status === 409) {
        setMessage(
          "מספר הטלפון הזה כבר רשום במכון. גשו לדלפק ובקשו קוד לקישור הטלפון.",
        );
      } else {
        setMessage("משהו השתבש. נסו שוב בעוד רגע.");
      }
    } catch {
      // No answer at all; everything typed stays, to send again.
      setMessage(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  function field(name: SignUpField, label: string, input: object = {}) {
    return (
      <p className={styles.field}>
        <label htmlFor={name}>{label}</label>
        <input
          id={name}
          value={values[name]}
          onChange={(event) =>
            setValues({ ...values, [name]: event.target.value })
          }
          aria-invalid={errors[name] ? true : undefined}
          aria-describedby={errors[name] ? `${name}-error` : undefined}
          required
          {...input}
        />
        {errors[name] && (
          <span id={`${name}-error`} role="alert">
            {errors[name]}
          </span>
        )}
      </p>
    );
  }

  return (
    <>
      <h1 className={styles.heading}>הרשמה</h1>
      <p className={styles.lead}>
        פעם ראשונה במכון? נרשמים כאן, ממלאים הצהרת בריאות ונכנסים לאימון.
      </p>
      <form onSubmit={submit} className={styles.panel}>
        {message && <p role="alert">{message}</p>}
        {field("first_name", "שם פרטי", {
          autoComplete: "given-name",
          maxLength: 50,
        })}
        {field("last_name", "שם משפחה", {
          autoComplete: "family-name",
          maxLength: 50,
        })}
        {field("phone", "מספר טלפון", {
          type: "tel",
          dir: "ltr",
          autoComplete: "tel",
          maxLength: 50,
        })}
        {field("date_of_birth", "תאריך לידה", {
          type: "date",
          autoComplete: "bday",
          // The picker offers no future dates; the server checks anyway.
          max: todayInIsrael(),
        })}
        <button type="submit" className={styles.wide} disabled={sending}>
          הרשמה
        </button>
      </form>
      <p className={styles.switch}>
        קיבלתם קוד בדלפק?{" "}
        <button type="button" onClick={onHaveCode}>
          קישור עם קוד
        </button>
      </p>
    </>
  );
}
