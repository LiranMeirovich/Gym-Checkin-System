// The Health form section of a customer's page (design doc: "Validity and
// access"; decisions 0031, 0041). Every staff member sees whether the form
// is valid or missing, and until when, and can open the form on this PC
// for a customer to fill in while it's missing. A form with a "yes" lets
// the customer in, but waits for the manager's review: only they see it
// as waiting (the server sends instructors "valid"), and they accept it or
// add a doctor's note. Only the manager sees the signed forms and their
// notes and can open them; the server checks that too, and logs every
// opening.
import { useState, type ChangeEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type Schemas } from "../backend/client";
import {
  formatDate,
  healthFormKey,
  healthFormsKey,
  type Customer,
} from "../customers";
import { can } from "../roles";
import { useSession } from "../session";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
  NO_CONNECTION_RELOAD,
} from "../../shared/NoConnection";
import ui from "../layout/ui.module.css";
import { StatusBadge } from "../../shared/Status";
import { type Tone } from "../../shared/Status";
import styles from "./CustomerHealthForm.module.css";

type Status = Schemas["HealthFormStatus"];
type FormSummary = Schemas["HealthFormSummary"];

// The server keeps a note at most this size on its longer side
// (`NOTE_MAX_SIDE`); shrinking first keeps the upload small and quick.
const NOTE_MAX_SIDE = 2500;

export async function fetchStatus(id: number): Promise<Status> {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/health-form",
    { params: { path: { customer_id: id } } },
  );
  if (data) return data;
  throw new Error(`GET health-form failed: ${response.status}`);
}

async function fetchForms(id: number): Promise<FormSummary[]> {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/health-forms",
    { params: { path: { customer_id: id } } },
  );
  if (data) return data.forms;
  throw new Error(`GET health-forms failed: ${response.status}`);
}

const STATE_BADGES: Record<Status["state"], { tone: Tone; text: string }> = {
  valid: { tone: "ok", text: "בתוקף" },
  needs_doctor_note: { tone: "warn", text: "ממתינה לבדיקה" },
  missing: { tone: "stop", text: "אין הצהרה בתוקף" },
};

function statusText(status: Status): string {
  const until = status.valid_until ? formatDate(status.valid_until) : "";
  switch (status.state) {
    case "valid":
      return `בתוקף עד ${until}`;
    case "needs_doctor_note":
      return `הלקוח סימן "כן" בשאלון (בתוקף עד ${until}). הכניסה מותרת; יש לפתוח את הטופס ולאשר אותו, או להוסיף אישור רפואי.`;
    case "missing":
      return "חסרה או פג תוקפה. אין כניסה עד שהלקוח ימלא טופס.";
  }
}

export function CustomerHealthForm({ customer }: { customer: Customer }) {
  const session = useSession();
  const { data, isPending, isError } = useQuery({
    queryKey: healthFormKey(customer.id),
    queryFn: () => fetchStatus(customer.id),
  });

  return (
    <section className={ui.panel}>
      <h2>הצהרת בריאות</h2>
      {isPending ? null : isError ? (
        <NoConnection />
      ) : (
        <>
          <div className={ui.statusLine}>
            <StatusBadge tone={STATE_BADGES[data.state].tone}>
              {STATE_BADGES[data.state].text}
            </StatusBadge>
            <span>{statusText(data)}</span>
          </div>
          {customer.active && data.state === "missing" && (
            <p>
              <Link
                className={ui.primaryLink}
                to={`/customers/${customer.id}/health-form`}
              >
                מילוי הצהרת הבריאות כאן, במחשב
              </Link>{" "}
              <span className={ui.muted}>(ללקוח בלי סמארטפון)</span>
            </p>
          )}
          {customer.active && data.state === "needs_doctor_note" && (
            <>
              {can(session, "health_forms.accept") && (
                <AcceptForm customer={customer} />
              )}
              <DoctorNoteUpload customer={customer} />
            </>
          )}
        </>
      )}
      {can(session, "health_forms.view_contents") && (
        <div className={ui.subsection}>
          <h3>טפסים חתומים</h3>
          <SignedForms customer={customer} />
        </div>
      )}
    </section>
  );
}

/** The manager accepts the form as it is, without a doctor's note. Can't
 * be undone: the acceptance stays on record (decision 0041). */
function AcceptForm({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function accept() {
    if (!window.confirm("לאשר את ההצהרה בלי אישור רפואי? אי אפשר לבטל.")) {
      return;
    }
    setMessage(null);
    setSending(true);
    try {
      const { data, error, response } = await api.POST(
        "/api/customers/{customer_id}/health-form/accept",
        { params: { path: { customer_id: customer.id } } },
      );
      if (data) {
        queryClient.setQueryData(healthFormKey(customer.id), data);
        void queryClient.invalidateQueries({
          queryKey: healthFormsKey(customer.id),
        });
        return;
      }
      if (response.status === 409 && error && "error" in error) {
        // The status changed since the page loaded: show what's there now.
        void queryClient.invalidateQueries({
          queryKey: healthFormKey(customer.id),
        });
        setMessage(
          error.error === "customer_inactive"
            ? "הלקוח לא פעיל. יש להפעיל אותו מחדש קודם."
            : "הטופס כבר לא ממתין לבדיקה.",
        );
      } else {
        setMessage("האישור נכשל. נסו שוב.");
      }
    } catch {
      setMessage(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      {message && <p role="alert">{message}</p>}
      <p>
        <button
          type="button"
          className={ui.primary}
          onClick={() => void accept()}
          disabled={sending}
        >
          אישור ההצהרה בלי אישור רפואי
        </button>
      </p>
    </>
  );
}

/** A photo or scan of the doctor's note, shrunk here and sent as a JPEG.
 * The server checks and re-encodes it again whatever this sends. */
function DoctorNoteUpload({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file) return;
    setMessage(null);
    setSending(true);
    try {
      let image: string;
      try {
        image = await shrinkToJpeg(file);
      } catch {
        setMessage("אי אפשר לקרוא את הקובץ. יש לבחור תמונה (JPEG או PNG).");
        return;
      }
      const { data, error, response } = await api.POST(
        "/api/customers/{customer_id}/health-form/doctor-note",
        { params: { path: { customer_id: customer.id } }, body: { image } },
      );
      if (data) {
        queryClient.setQueryData(healthFormKey(customer.id), data);
        void queryClient.invalidateQueries({
          queryKey: healthFormsKey(customer.id),
        });
        return;
      }
      if (response.status === 400) {
        setMessage("התמונה לא התקבלה: קטנה, גדולה או לא ברורה מדי. נסו שוב.");
      } else if (response.status === 409 && error && "error" in error) {
        // The status changed since the page loaded: show what's there now.
        void queryClient.invalidateQueries({
          queryKey: healthFormKey(customer.id),
        });
        setMessage(
          error.error === "customer_inactive"
            ? "הלקוח לא פעיל. יש להפעיל אותו מחדש קודם."
            : "הטופס כבר לא ממתין לבדיקה.",
        );
      } else {
        setMessage("השמירה נכשלה. נסו שוב.");
      }
    } catch {
      setMessage(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
      // The same file can be chosen again after a failure.
      input.value = "";
    }
  }

  return (
    <>
      {message && <p role="alert">{message}</p>}
      <div className={styles.upload}>
        <label htmlFor={`doctor-note-${customer.id}`}>
          הוספת אישור רפואי (צילום או סריקה)
        </label>
        <input
          id={`doctor-note-${customer.id}`}
          type="file"
          accept="image/jpeg,image/png"
          disabled={sending}
          onChange={(event) => void upload(event)}
        />
        {sending && <span className={ui.muted}>שולח…</span>}
      </div>
    </>
  );
}

/** The image, upright and at most NOTE_MAX_SIDE on its longer side, as a
 * JPEG data URL. Throws if the browser can't read it as an image. */
async function shrinkToJpeg(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file, {
    imageOrientation: "from-image",
  });
  try {
    const scale = Math.min(
      1,
      NOTE_MAX_SIDE / Math.max(bitmap.width, bitmap.height),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no 2D canvas");
    // A PNG's transparent parts would turn black in a JPEG.
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
  } finally {
    bitmap.close();
  }
}

function SignedForms({ customer }: { customer: Customer }) {
  const [message, setMessage] = useState<string | null>(null);
  // A file whose new tab the browser blocked.
  const [blocked, setBlocked] = useState<string | null>(null);
  const { data, isPending, isError } = useQuery({
    queryKey: healthFormsKey(customer.id),
    queryFn: () => fetchForms(customer.id),
  });

  /** Open a form's PDF or a note's image in a new tab. */
  async function open(
    fetchFile: () => Promise<{ data?: unknown; response: Response }>,
  ) {
    setMessage(null);
    setBlocked(null);
    // Opened before the request, while the click still counts as the
    // user's: a window opened after an await is often blocked.
    const tab = window.open("", "_blank");
    try {
      const { data: file, response } = await fetchFile();
      if (!file) {
        tab?.close();
        setMessage(
          response.status === 403
            ? "אין הרשאה לפתוח את הקובץ."
            : NO_CONNECTION_RELOAD,
        );
        return;
      }
      // The file lives only in this browser's memory, never on disk, and
      // is let go after a minute.
      const url = URL.createObjectURL(file as Blob);
      if (tab) tab.location.assign(url);
      // Pop-ups blocked: a link the manager clicks instead.
      else setBlocked(url);
      setTimeout(() => {
        URL.revokeObjectURL(url);
        setBlocked((shown) => (shown === url ? null : shown));
      }, 60_000);
    } catch {
      tab?.close();
      setMessage(NO_CONNECTION_RELOAD);
    }
  }

  function openForm(form: FormSummary) {
    return open(() =>
      api.POST("/api/customers/{customer_id}/health-forms/{form_id}/open", {
        params: { path: { customer_id: customer.id, form_id: form.id } },
        parseAs: "blob",
      }),
    );
  }

  function openNote(noteId: number) {
    return open(() =>
      api.POST("/api/customers/{customer_id}/doctor-notes/{note_id}/open", {
        params: { path: { customer_id: customer.id, note_id: noteId } },
        parseAs: "blob",
      }),
    );
  }

  if (isPending) return null;
  if (isError) return <NoConnection />;
  if (data.length === 0) {
    return <p className={ui.muted}>הלקוח עוד לא מילא טופס.</p>;
  }
  return (
    <>
      {message && <p role="alert">{message}</p>}
      {blocked && (
        <p role="status">
          הדפדפן חסם חלון חדש.{" "}
          <a href={blocked} target="_blank" rel="noreferrer">
            הצגת הקובץ
          </a>
        </p>
      )}
      <div className={ui.flushTable}>
        <table>
          <thead>
            <tr>
              <th>נחתם</th>
              <th>בתוקף עד</th>
              <th>חותם</th>
              <th>אישור רפואי</th>
              <th className={ui.rowAction}>
                <span className="visually-hidden">טופס</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((form) => (
              <tr key={form.id}>
                <td>{formatDate(form.signed_on)}</td>
                <td>{formatDate(form.expires_on)}</td>
                <td>
                  {form.signer_name}
                  {form.signed_by_guardian && " (הורה)"}
                </td>
                <td>
                  {!form.needs_doctor_note ? (
                    "לא נדרש"
                  ) : form.doctor_note_ids.length === 0 ? (
                    form.accepted ? (
                      "אושר בלי אישור רפואי"
                    ) : (
                      <StatusBadge tone="warn">ממתין לבדיקה</StatusBadge>
                    )
                  ) : (
                    form.doctor_note_ids.map((noteId, index) => (
                      <button
                        key={noteId}
                        type="button"
                        onClick={() => void openNote(noteId)}
                      >
                        {form.doctor_note_ids.length === 1
                          ? "פתיחת האישור"
                          : `פתיחת אישור ${index + 1}`}
                      </button>
                    ))
                  )}
                </td>
                <td className={ui.rowAction}>
                  <button type="button" onClick={() => void openForm(form)}>
                    פתיחת הטופס
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={ui.note}>כל פתיחה של טופס או אישור נרשמת ביומן הפעילות.</p>
    </>
  );
}
