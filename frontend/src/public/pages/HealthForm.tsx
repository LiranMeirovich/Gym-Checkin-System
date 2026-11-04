// The health declaration (design doc: "Health form"; decision 0031): the
// official form's wording from the server, every question answered yes
// or no, a confirmation box, the signer's name and a finger-drawn
// signature. A parent signs for an under-18 (the server says when).
//
// Kept apart from the check-in page, so the gym-device version (feature 4)
// can reuse it.
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { SignaturePad } from "../components/SignaturePad";
import { formatDay } from "../dates";

type Page = Schemas["HealthFormPage"];
type Status = Schemas["HealthFormStatus"];
type Field = Schemas["FormField"];

const FIELD_ERRORS: Record<Field, string> = {
  answers: "יש לענות כן או לא על כל השאלות.",
  details:
    "הפירוט ארוך מדי או כולל תווים שאי אפשר להדפיס (עד 200 תווים, בעברית או באותיות לועזיות).",
  gender: "יש לבחור מין.",
  signer_name: "יש לכתוב שם מלא, באותיות עבריות או לועזיות.",
  confirmed: "יש לסמן את תיבת האישור.",
  signature: "יש לחתום בתיבת החתימה.",
};

async function fetchForm(): Promise<Page> {
  const { data, response } = await api.GET("/api/health-form");
  if (data) return data;
  throw new Error(`GET /api/health-form failed: ${response.status}`);
}

type Props = {
  /** Called with the new status once the form is saved. */
  onSigned: (status: Status) => void;
};

const VERSION_CHANGED = "הטופס עודכן בזמן שמילאתם אותו. יש למלא אותו מחדש.";

export function HealthForm({ onSigned }: Props) {
  // Kept here, not in the form: a new version remounts the form, which
  // would drop the message saying why it's empty again.
  const [versionChanged, setVersionChanged] = useState(false);
  const {
    data: page,
    isPending,
    isError,
    refetch,
  } = useQuery({ queryKey: ["health-form"], queryFn: fetchForm });

  if (isPending) return null;
  if (isError) return <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>;
  return (
    <>
      {versionChanged && <p role="alert">{VERSION_CHANGED}</p>}
      <FilledForm
        key={page.version}
        page={page}
        onSigned={onSigned}
        onVersionChanged={() => {
          setVersionChanged(true);
          void refetch();
        }}
      />
    </>
  );
}

function FilledForm({
  page,
  onSigned,
  onVersionChanged,
}: {
  page: Page;
  onSigned: (status: Status) => void;
  onVersionChanged: () => void;
}) {
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [details, setDetails] = useState<Record<string, string>>({});
  const [gender, setGender] = useState("");
  const [signerName, setSignerName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [signature, setSignature] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [sending, setSending] = useState(false);

  const guardian = page.guardian_consent !== null;
  const unanswered = page.questions.some((q) => !(q.key in answers));

  async function submit(event: FormEvent) {
    event.preventDefault();
    // The server checks everything again; this only saves a round trip.
    const missing: string[] = [];
    if (unanswered) missing.push(FIELD_ERRORS.answers);
    if (!gender) missing.push(FIELD_ERRORS.gender);
    if (!signerName.trim()) missing.push(FIELD_ERRORS.signer_name);
    if (!confirmed) missing.push(FIELD_ERRORS.confirmed);
    if (!signature) missing.push(FIELD_ERRORS.signature);
    setErrors(missing);
    if (missing.length > 0 || !signature) return;

    setSending(true);
    try {
      const { data, error, response } = await api.POST("/api/health-form", {
        body: {
          version: page.version,
          answers,
          details,
          gender,
          signer_name: signerName,
          confirmed,
          signature,
        },
      });
      if (data) {
        onSigned(data);
        return;
      }
      if (response.status === 409) {
        onVersionChanged();
        return;
      }
      if (response.status === 400 && error && "errors" in error) {
        setErrors(
          (Object.keys(error.errors) as Field[]).map(
            (field) => FIELD_ERRORS[field] ?? FIELD_ERRORS.answers,
          ),
        );
        return;
      }
      setErrors(["משהו השתבש. נסו שוב בעוד רגע."]);
    } catch {
      setErrors(["אין חיבור לשרת. נסו שוב."]);
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <h1>{page.title}</h1>

      <p>
        שם פרטי ושם משפחה: {page.customer_name}
        <br />
        תאריך לידה: <bdi>{formatDay(page.date_of_birth)}</bdi>
        <br />
        מספר טלפון: <bdi>{page.phone}</bdi>
      </p>

      <fieldset>
        <legend>מין</legend>
        <label>
          <input
            type="radio"
            name="gender"
            value="male"
            checked={gender === "male"}
            onChange={() => setGender("male")}
          />{" "}
          זכר
        </label>{" "}
        <label>
          <input
            type="radio"
            name="gender"
            value="female"
            checked={gender === "female"}
            onChange={() => setGender("female")}
          />{" "}
          נקבה
        </label>
      </fieldset>
      <p>
        <small>{page.wording_note}</small>
      </p>

      <h2>{page.part_a_title}</h2>
      {page.part_a_notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
      <p>
        <strong>{page.questions_intro}</strong>
      </p>
      <ol>
        {page.questions.map((question) => (
          <li key={question.key}>
            <fieldset>
              <legend>{question.text}</legend>
              <label>
                <input
                  type="radio"
                  name={question.key}
                  checked={answers[question.key] === true}
                  onChange={() =>
                    setAnswers((all) => ({ ...all, [question.key]: true }))
                  }
                />{" "}
                כן
              </label>{" "}
              <label>
                <input
                  type="radio"
                  name={question.key}
                  checked={answers[question.key] === false}
                  onChange={() =>
                    setAnswers((all) => ({ ...all, [question.key]: false }))
                  }
                />{" "}
                לא
              </label>
              {question.has_details && (
                <p>
                  <label>
                    פירוט:{" "}
                    <input
                      value={details[question.key] ?? ""}
                      maxLength={200}
                      onChange={(event) =>
                        setDetails((all) => ({
                          ...all,
                          [question.key]: event.target.value,
                        }))
                      }
                    />
                  </label>
                </p>
              )}
            </fieldset>
          </li>
        ))}
      </ol>

      <h2>{page.part_b_title}</h2>
      {page.declaration.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
      <p>
        תוקף ההצהרה עד: <bdi>{formatDay(page.valid_until_if_signed)}</bdi>
      </p>

      {guardian && (
        <>
          <h2>{page.guardian_title}</h2>
          <p>{page.guardian_consent}</p>
        </>
      )}

      <p>
        <label>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />{" "}
          {guardian
            ? "קראתי את הטופס ואני מאשר/ת את ההצהרה וההסכמה."
            : "קראתי את הטופס ואני מאשר/ת את ההצהרה."}
        </label>
      </p>
      <p>
        <label htmlFor="signer-name">
          {guardian ? "שם ההורה" : "שם ושם משפחה"}
        </label>{" "}
        <input
          id="signer-name"
          autoComplete="name"
          value={signerName}
          maxLength={100}
          onChange={(event) => setSignerName(event.target.value)}
        />
      </p>
      <SignaturePad
        label={guardian ? "חתימת הורה" : "חתימה"}
        onChange={setSignature}
      />

      {errors.length > 0 && (
        <ul role="alert">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <p>
        <button type="submit" disabled={sending}>
          שליחת הטופס
        </button>
      </p>
    </form>
  );
}
