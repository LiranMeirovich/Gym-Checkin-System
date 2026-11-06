// First-run setup: the gym's name and the first manager (design doc:
// "First run"). Exists only on a fresh install; afterwards the API answers
// 404 and this page goes to the lock screen.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router";
import { api, type Schemas } from "../backend/client";
import { BRANDING_KEY } from "../branding";
import { useStartSession } from "../session";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
} from "../../shared/NoConnection";
import { EntryLayout } from "../layout/EntryLayout";
import styles from "../layout/EntryLayout.module.css";

type Field = keyof Schemas["SetupRequest"];

// Shown next to the field. Each field has one rule, so one message each.
const ERRORS: Record<Field, string> = {
  gym_name: "שם המכון: 1 עד 100 תווים",
  display_name: "שם: 1 עד 50 תווים, בלי תווים נסתרים",
  pin: "קוד: 6 עד 12 ספרות, לא ספרה אחת חוזרת ולא רצף (כמו 123456)",
  pin_again: "הקודים אינם זהים",
};

const EMPTY: Schemas["SetupRequest"] = {
  gym_name: "",
  display_name: "",
  pin: "",
  pin_again: "",
};

async function fetchSetupNeeded(): Promise<boolean> {
  const { data, response } = await api.GET("/api/setup");
  if (data) return true;
  if (response.status === 404) return false;
  throw new Error(`GET /api/setup failed: ${response.status}`);
}

export function Setup() {
  const {
    data: needed,
    isPending,
    isError,
  } = useQuery({
    queryKey: ["setup"],
    queryFn: fetchSetupNeeded,
    gcTime: 0,
  });

  if (isPending) return null;
  if (isError) return <NoConnection />;
  if (!needed) return <Navigate to="/login" replace />;
  return <SetupForm />;
}

function SetupForm() {
  const navigate = useNavigate();
  const startSession = useStartSession();
  const queryClient = useQueryClient();
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setFormError(null);
    try {
      const { data, error, response } = await api.POST("/api/setup", {
        body: values,
      });
      if (data) {
        startSession(data);
        // The header shows the gym name that was just saved.
        void queryClient.invalidateQueries({ queryKey: BRANDING_KEY });
        navigate("/", { replace: true });
        return;
      }
      if (response.status === 404) {
        // Someone else finished setup in the meantime.
        navigate("/login", { replace: true });
        return;
      }
      // Names stay; PINs are cleared.
      setValues({ ...values, pin: "", pin_again: "" });
      if (error && "errors" in error) {
        const fields = Object.keys(error.errors) as Field[];
        setErrors(Object.fromEntries(fields.map((f) => [f, ERRORS[f]])));
      } else {
        setErrors({});
        setFormError("השמירה נכשלה. נסו שוב.");
      }
    } catch {
      // The request never got an answer (server down, network error);
      // everything typed stays, so it can simply be sent again.
      setFormError(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  function field(name: Field, label: string, pin = false) {
    return (
      <p>
        <label htmlFor={name}>{label}</label>{" "}
        <input
          id={name}
          value={values[name]}
          onChange={(event) =>
            setValues({ ...values, [name]: event.target.value })
          }
          required
          {...(pin
            ? { type: "password", inputMode: "numeric", pattern: "[0-9]{6,12}" }
            : { maxLength: name === "gym_name" ? 100 : 50 })}
        />{" "}
        {errors[name] && <span role="alert">{errors[name]}</span>}
      </p>
    );
  }

  return (
    <EntryLayout>
      <h1 className={styles.heading}>הגדרה ראשונה</h1>
      <p className={styles.lead}>
        פרטי המכון וחשבון המנהל הראשון. את חשבונות המדריכים מוסיפים אחר כך, מתוך
        המערכת.
      </p>
      <form className={styles.panel} onSubmit={submit} autoComplete="off">
        {formError && <p role="alert">{formError}</p>}
        {field("gym_name", "שם המכון")}
        {field("display_name", "השם שלך (יופיע במסך הנעילה)")}
        {field("pin", "קוד אישי (6 עד 12 ספרות)", true)}
        {field("pin_again", "הקוד שוב", true)}
        <p>
          <button type="submit" disabled={sending}>
            שמירה וכניסה
          </button>
        </p>
      </form>
    </EntryLayout>
  );
}
