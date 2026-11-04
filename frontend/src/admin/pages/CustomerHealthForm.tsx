// The Health form section of a customer's page (design doc: "Validity and
// access"; decision 0031). Every staff member sees whether the form is
// valid, needs a doctor's note, or is missing, and until when. Only the
// manager sees the signed forms and can open one; the server checks that
// too, and logs every opening.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDate, isManager, type Customer } from "../customers";
import { useSession } from "../session";

type Status = Schemas["HealthFormStatus"];
type FormSummary = Schemas["HealthFormSummary"];

const NO_CONNECTION = "אין חיבור לשרת. נסו לרענן את הדף.";

function healthFormKey(id: number) {
  return ["customers", id, "health-form"] as const;
}

function healthFormsKey(id: number) {
  return ["customers", id, "health-forms"] as const;
}

async function fetchStatus(id: number): Promise<Status> {
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
        <p>{statusText(data)}</p>
      )}
      {isManager(session) && <SignedForms customer={customer} />}
    </section>
  );
}

function SignedForms({ customer }: { customer: Customer }) {
  const [message, setMessage] = useState<string | null>(null);
  // A PDF whose new tab the browser blocked.
  const [blocked, setBlocked] = useState<string | null>(null);
  const { data, isPending, isError } = useQuery({
    queryKey: healthFormsKey(customer.id),
    queryFn: () => fetchForms(customer.id),
  });

  async function open(form: FormSummary) {
    setMessage(null);
    setBlocked(null);
    // Opened before the request, while the click still counts as the
    // user's: a window opened after an await is often blocked.
    const tab = window.open("", "_blank");
    try {
      const { data: pdf, response } = await api.POST(
        "/api/customers/{customer_id}/health-forms/{form_id}/open",
        {
          params: { path: { customer_id: customer.id, form_id: form.id } },
          parseAs: "blob",
        },
      );
      if (!pdf) {
        tab?.close();
        setMessage(
          response.status === 403 ? "אין הרשאה לפתוח טפסים." : NO_CONNECTION,
        );
        return;
      }
      // The PDF lives only in this browser's memory, never on disk, and
      // is let go after a minute.
      const url = URL.createObjectURL(pdf as Blob);
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
            הצגת הטופס
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
              <td>{form.needs_doctor_note ? "נדרש" : "לא נדרש"}</td>
              <td>
                <button type="button" onClick={() => void open(form)}>
                  פתיחה
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        <small>כל פתיחה של טופס נרשמת ביומן הפעילות.</small>
      </p>
    </>
  );
}
