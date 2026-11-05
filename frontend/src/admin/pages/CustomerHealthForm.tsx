// The Health form section of a customer's page (design doc: "Validity and
// access"; decision 0031). Every staff member sees whether the form is
// valid, needs a doctor's note, or is missing, and until when; can open
// the form on this PC for a customer to fill in while it's missing; and
// can add a doctor's note to a form with a "yes". Only the manager sees
// the signed forms and their notes and can open them; the server checks
// that too, and logs every opening.
import { useState, type ChangeEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type Schemas } from "../backend/client";
import {
  formatDate,
  healthFormKey,
  healthFormsKey,
  isManager,
  type Customer,
} from "../customers";
import { useSession } from "../session";

type Status = Schemas["HealthFormStatus"];
type FormSummary = Schemas["HealthFormSummary"];

const NO_CONNECTION = "אין חיבור לשרת. נסו לרענן את הדף.";

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

function statusText(status: Status): string {
  const until = status.valid_until ? formatDate(status.valid_until) : "";
  switch (status.state) {
    case "valid":
      return `בתוקף עד ${until}`;
    case "needs_doctor_note":
      return `חסר אישור רפואי: הלקוח סימן "כן" בשאלון (הטופס עד ${until}). אין כניסה עד שיתקבל אישור.`;
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
    <section>
      <h2>הצהרת בריאות</h2>
      {isPending ? null : isError ? (
        <p role="alert">{NO_CONNECTION}</p>
      ) : (
        <>
          <p>{statusText(data)}</p>
          {customer.active && data.state === "missing" && (
            <p>
              <Link to={`/customers/${customer.id}/health-form`}>
                מילוי הצהרת הבריאות כאן, במחשב
              </Link>{" "}
              <small>(ללקוח בלי סמארטפון)</small>
            </p>
          )}
          {customer.active && data.state === "needs_doctor_note" && (
            <DoctorNoteUpload customer={customer} />
          )}
        </>
      )}
      {isManager(session) && <SignedForms customer={customer} />}
    </section>
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
            : "הטופס כבר לא ממתין לאישור רפואי.",
        );
      } else {
        setMessage("השמירה נכשלה. נסו שוב.");
      }
    } catch {
      setMessage("אין חיבור לשרת. נסו שוב.");
    } finally {
      setSending(false);
      // The same file can be chosen again after a failure.
      input.value = "";
    }
  }

  return (
    <>
      {message && <p role="alert">{message}</p>}
      <p>
        <label>
          הוספת אישור רפואי (צילום או סריקה):{" "}
          <input
            type="file"
            accept="image/jpeg,image/png"
            disabled={sending}
            onChange={(event) => void upload(event)}
          />
        </label>
        {sending && " שולח…"}
      </p>
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
          response.status === 403 ? "אין הרשאה לפתוח את הקובץ." : NO_CONNECTION,
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
      setMessage(NO_CONNECTION);
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
  if (isError) return <p role="alert">{NO_CONNECTION}</p>;
  if (data.length === 0) return <p>הלקוח עוד לא מילא טופס.</p>;
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
      <table>
        <thead>
          <tr>
            <th>נחתם</th>
            <th>בתוקף עד</th>
            <th>חותם</th>
            <th>אישור רפואי</th>
            <th />
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
                {!form.needs_doctor_note
                  ? "לא נדרש"
                  : form.doctor_note_ids.length === 0
                    ? "נדרש, חסר"
                    : form.doctor_note_ids.map((noteId, index) => (
                        <button
                          key={noteId}
                          type="button"
                          onClick={() => void openNote(noteId)}
                        >
                          {form.doctor_note_ids.length === 1
                            ? "פתיחת האישור"
                            : `פתיחת אישור ${index + 1}`}
                        </button>
                      ))}
              </td>
              <td>
                <button type="button" onClick={() => void openForm(form)}>
                  פתיחת הטופס
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        <small>כל פתיחה של טופס או אישור נרשמת ביומן הפעילות.</small>
      </p>
    </>
  );
}
