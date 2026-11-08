// The health declaration (design doc: "Health form"; decision 0031): the
// official form's wording from the server, every question answered yes
// or no, a confirmation box, the signer's name and a finger-drawn
// signature. A parent signs for an under-18 (the server says when).
//
// Shared by both builds: the customer's phone (public app) and the admin
// PC at the desk (decision 0031). Neither app's API client is imported
// here; each passes its own `load` and `submit`. The types below mirror
// both APIs' shapes, so if either API drifts, its caller stops
// type-checking.
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { SignaturePad } from "./SignaturePad";
import { formatDay } from "./dates";
import { NoConnection, NO_CONNECTION_TRY_AGAIN } from "./NoConnection";
import styles from "./HealthForm.module.css";

export type HealthFormPage = {
  version: string;
  title: string;
  customer_name: string;
  date_of_birth: string;
  phone: string;
  wording_note: string;
  part_a_title: string;
  part_a_notes: string[];
  questions_intro: string;
  questions: { key: string; text: string; has_details: boolean }[];
  part_b_title: string;
  declaration: string[];
  guardian_title: string;
  guardian_consent: string | null;
  valid_until_if_signed: string;
};

export type HealthFormField =
  "answers" | "details" | "gender" | "signer_name" | "confirmed" | "signature";

/** The filled-in form, as both APIs take it. */
export type FilledInForm = {
  version: string;
  answers: Record<string, boolean>;
  details: Record<string, string>;
  gender: string;
  signer_name: string;
  confirmed: boolean;
  signature: string;
};

/** What became of a submit; the caller turns its API's answer into one. */
export type SubmitOutcome<Status> =
  | { outcome: "signed"; status: Status }
  // 409: the form changed while it was open; it's loaded again.
  | { outcome: "version_changed" }
  // 400: these fields break their rules.
  | { outcome: "invalid"; fields: HealthFormField[] }
  // Anything else, with the text to show.
  | { outcome: "refused"; message: string };

type Page = HealthFormPage;
type Field = HealthFormField;

const FIELD_ERRORS: Record<Field, string> = {
  answers: "יש לענות כן או לא על כל השאלות.",
  details:
    "הפירוט ארוך מדי או כולל תווים שאי אפשר להדפיס (עד 200 תווים, בעברית או באותיות לועזיות).",
  gender: "יש לבחור מין.",
  signer_name: "יש לכתוב שם מלא, באותיות עבריות או לועזיות.",
  confirmed: "יש לסמן את תיבת האישור.",
  signature: "יש לחתום בתיבת החתימה.",
};

type Props<Status> = {
  /** The TanStack Query key the form is cached under. */
  queryKey: readonly unknown[];
  /** Loads the current form; throws when it can't. */
  load: () => Promise<Page>;
  /** Sends the filled-in form; throws only when the server can't be reached. */
  submit: (form: FilledInForm) => Promise<SubmitOutcome<Status>>;
  /** Called with the new status once the form is saved. */
  onSigned: (status: Status) => void;
};

const VERSION_CHANGED = "הטופס עודכן בזמן שמילאתם אותו. יש למלא אותו מחדש.";

export function HealthForm<Status>({
  queryKey,
  load,
  submit,
  onSigned,
}: Props<Status>) {
  // Kept here, not in the form: a new version remounts the form, which
  // would drop the message saying why it's empty again.
  const [versionChanged, setVersionChanged] = useState(false);
  const {
    data: page,
    isPending,
    isError,
    refetch,
  } = useQuery({ queryKey, queryFn: load });

  if (isPending) return null;
  if (isError) return <NoConnection />;
  return (
    <>
      {versionChanged && <p role="alert">{VERSION_CHANGED}</p>}
      <FilledForm
        key={page.version}
        page={page}
        submit={submit}
        onSigned={onSigned}
        onVersionChanged={() => {
          setVersionChanged(true);
          void refetch();
        }}
      />
    </>
  );
}

function FilledForm<Status>({
  page,
  submit: send,
  onSigned,
  onVersionChanged,
}: {
  page: Page;
  submit: (form: FilledInForm) => Promise<SubmitOutcome<Status>>;
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
      const result = await send({
        version: page.version,
        answers,
        details,
        gender,
        signer_name: signerName,
        confirmed,
        signature,
      });
      switch (result.outcome) {
        case "signed":
          onSigned(result.status);
          return;
        case "version_changed":
          onVersionChanged();
          return;
        case "invalid":
          setErrors(
            result.fields.map(
              (field) => FIELD_ERRORS[field] ?? FIELD_ERRORS.answers,
            ),
          );
          return;
        case "refused":
          setErrors([result.message]);
          return;
      }
    } catch {
      setErrors([NO_CONNECTION_TRY_AGAIN]);
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className={styles.form}>
      <h1 className={styles.title}>{page.title}</h1>

      <dl className={styles.person}>
        <dt>שם פרטי ושם משפחה</dt>
        <dd>{page.customer_name}</dd>
        <dt>תאריך לידה</dt>
        <dd>
          <bdi>{formatDay(page.date_of_birth)}</bdi>
        </dd>
        <dt>מספר טלפון</dt>
        <dd>
          <bdi>{page.phone}</bdi>
        </dd>
      </dl>

      <fieldset className={styles.gender}>
        <legend>מין</legend>
        <div className={styles.answers}>
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
        </div>
      </fieldset>
      <p className={styles.small}>{page.wording_note}</p>

      <h2 className={styles.part}>{page.part_a_title}</h2>
      {page.part_a_notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
      <p>
        <strong>{page.questions_intro}</strong>
      </p>
      <ol className={styles.questions}>
        {page.questions.map((question) => (
          <li key={question.key} className={styles.question}>
            <fieldset>
              <legend>{question.text}</legend>
              <div className={styles.answers}>
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
              </div>
              {question.has_details && (
                <p className={styles.details}>
                  <label>
                    פירוט
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

      <h2 className={styles.part}>{page.part_b_title}</h2>
      {page.declaration.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
      <p className={styles.validUntil}>
        תוקף ההצהרה עד: <bdi>{formatDay(page.valid_until_if_signed)}</bdi>
      </p>

      {guardian && (
        <>
          <h2 className={styles.part}>{page.guardian_title}</h2>
          <p>{page.guardian_consent}</p>
        </>
      )}

      <div className={styles.signing}>
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
          </label>
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
      </div>

      {errors.length > 0 && (
        <ul role="alert" className={styles.errors}>
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <button type="submit" className={styles.send} disabled={sending}>
        שליחת הטופס
      </button>
    </form>
  );
}
