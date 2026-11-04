// The Phones section of a customer's page: issuing a link code for the
// customer to type on their phone, and the phones linked so far, each with
// Unlink. The code is shown only here, once; the server keeps its hash.
//
// The list doesn't poll while a code is on screen: every API request
// counts as activity for the auto-lock, so polling would keep the desk
// unlocked. A Refresh button shows a phone the customer just linked.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDate, formatTime, phonesKey, type Customer } from "../customers";

type LinkedPhone = Schemas["LinkedPhone"];
type IssuedCode = Schemas["LinkCodeIssued"];

const NO_CONNECTION = "אין חיבור לשרת. נסו שוב.";

async function fetchPhones(id: number): Promise<LinkedPhone[]> {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/phones",
    { params: { path: { customer_id: id } } },
  );
  if (data) return data.phones;
  throw new Error(`GET /api/customers/${id}/phones failed: ${response.status}`);
}

export function CustomerPhones({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const [issued, setIssued] = useState<IssuedCode | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const { data, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: phonesKey(customer.id),
    queryFn: () => fetchPhones(customer.id),
  });

  async function issue() {
    setSending(true);
    setMessage(null);
    try {
      const { data: code, response } = await api.POST(
        "/api/customers/{customer_id}/link-code",
        { params: { path: { customer_id: customer.id } } },
      );
      if (code) setIssued(code);
      else if (response.status === 409) {
        setMessage("הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.");
      } else setMessage("הפקת הקוד נכשלה. נסו שוב.");
    } catch {
      setMessage(NO_CONNECTION);
    } finally {
      setSending(false);
    }
  }

  async function unlink(phone: LinkedPhone) {
    if (!window.confirm("לנתק את הטלפון? הלקוח יצטרך קוד חדש כדי לקשר אותו.")) {
      return;
    }
    setSending(true);
    setMessage(null);
    try {
      const { data: list } = await api.POST(
        "/api/customers/{customer_id}/phones/{phone_id}/unlink",
        {
          params: { path: { customer_id: customer.id, phone_id: phone.id } },
        },
      );
      if (list) queryClient.setQueryData(phonesKey(customer.id), list.phones);
      else {
        setMessage("הניתוק נכשל. מוצג המצב העדכני.");
        void refetch();
      }
    } catch {
      setMessage(NO_CONNECTION);
    } finally {
      setSending(false);
    }
  }

  return (
    <section>
      <h2>טלפונים מקושרים</h2>
      {message && <p role="alert">{message}</p>}

      {customer.active && (
        <>
          {issued && (
            <p role="status">
              קוד קישור:{" "}
              <strong dir="ltr" style={{ fontSize: "2em" }}>
                {issued.code}
              </strong>
              <br />
              הלקוח מזין בטלפון את מספר הטלפון שלו ואת הקוד. הקוד תקף עד{" "}
              {formatTime(issued.expires_at)}, לשימוש אחד. קוד חדש מבטל את
              הקודם.
            </p>
          )}
          <p>
            <button type="button" onClick={issue} disabled={sending}>
              {issued ? "קוד חדש" : "קישור טלפון"}
            </button>
          </p>
        </>
      )}

      {isPending ? null : isError ? (
        <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>
      ) : data.length === 0 ? (
        <p>אין טלפון מקושר.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>מכשיר</th>
              <th>קושר</th>
              <th>שימוש אחרון</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((phone) => (
              <tr key={phone.id}>
                <td title={phone.user_agent}>{deviceName(phone.user_agent)}</td>
                <td>{formatDate(phone.linked_at)}</td>
                <td>{formatDate(phone.last_used_at)}</td>
                <td>
                  <button
                    type="button"
                    onClick={() => void unlink(phone)}
                    disabled={sending}
                  >
                    ניתוק
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!isPending && (
        <p>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            רענון הרשימה
          </button>
        </p>
      )}
    </section>
  );
}

/** A rough name from the browser's user agent, enough for staff to tell
 * two phones apart. The full text is in the cell's tooltip. */
function deviceName(userAgent: string): string {
  if (/iPhone/.test(userAgent)) return "iPhone";
  if (/iPad/.test(userAgent)) return "iPad";
  if (/Android/.test(userAgent)) return "Android";
  return "מכשיר אחר";
}
