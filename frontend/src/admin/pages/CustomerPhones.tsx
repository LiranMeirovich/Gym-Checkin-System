// The Phones section of a customer's page: issuing a link code for the
// customer to type on their phone, and the phones linked so far, each with
// Unlink. The code is shown only here, once; the server keeps its hash.
//
// While a code is on screen (until it expires), the list refreshes itself
// every few seconds as background refreshes, which don't hold off the
// auto-lock (`usePolledQuery`). When a phone that wasn't there before shows
// up, the customer has used the code: it's hidden and the new phone is in
// the list. A code is issued only once the list has loaded, so "before" is
// known.
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDate, formatTime, phonesKey, type Customer } from "../customers";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
} from "../../shared/NoConnection";
import ui from "../layout/ui.module.css";
import { usePolledQuery } from "../polling";
import styles from "./CustomerPhones.module.css";

type LinkedPhone = Schemas["LinkedPhone"];
type IssuedCode = Schemas["LinkCodeIssued"];

// How often the list refreshes while a code waits to be used.
const WHILE_CODE_SHOWS_MS = 4_000;

async function fetchPhones(
  id: number,
  headers: Record<string, string>,
): Promise<LinkedPhone[]> {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/phones",
    { params: { path: { customer_id: id } }, headers },
  );
  if (data) return data.phones;
  throw new Error(`GET /api/customers/${id}/phones failed: ${response.status}`);
}

export function CustomerPhones({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const [issued, setIssued] = useState<IssuedCode | null>(null);
  // The phones linked when the code was issued: a new one means it was used.
  const [linkedBefore, setLinkedBefore] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const { data, isPending, isError, refetch } = usePolledQuery({
    queryKey: phonesKey(customer.id),
    fetch: (headers) => fetchPhones(customer.id, headers),
    everyMs: (phones) =>
      issued && !codeUsed(phones, linkedBefore) ? WHILE_CODE_SHOWS_MS : false,
    until: issued ? Date.parse(issued.expires_at) : undefined,
  });
  const linked = issued !== null && codeUsed(data, linkedBefore);
  const shownCode = linked ? null : issued;

  async function issue() {
    if (data === undefined) return;
    setSending(true);
    setMessage(null);
    try {
      const { data: code, response } = await api.POST(
        "/api/customers/{customer_id}/link-code",
        { params: { path: { customer_id: customer.id } } },
      );
      if (code) {
        setLinkedBefore(new Set(data.map((phone) => phone.id)));
        setIssued(code);
      } else if (response.status === 409) {
        setMessage("הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.");
      } else setMessage("הפקת הקוד נכשלה. נסו שוב.");
    } catch {
      setMessage(NO_CONNECTION_TRY_AGAIN);
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
    // A used code mustn't come back when its phone is unlinked.
    if (linked) setIssued(null);
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
      setMessage(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  return (
    <section className={ui.panel}>
      <h2>טלפונים מקושרים</h2>
      {message && <p role="alert">{message}</p>}
      {linked && <p role="status">הטלפון קושר.</p>}

      {customer.active && (
        <>
          {shownCode && (
            <div role="status" className={styles.code}>
              <span className={styles.codeLabel}>קוד קישור</span>
              <strong className={styles.codeDigits} dir="ltr">
                {shownCode.code}
              </strong>
              <span className={styles.codeHelp}>
                הלקוח מזין בטלפון את מספר הטלפון שלו ואת הקוד. הקוד תקף עד{" "}
                {formatTime(shownCode.expires_at)}, לשימוש אחד. קוד חדש מבטל את
                הקודם.
              </span>
            </div>
          )}
          <p>
            <button
              type="button"
              className={shownCode ? undefined : ui.primary}
              onClick={issue}
              // The phones linked now must be known, to tell when a new
              // one appears.
              disabled={sending || data === undefined}
            >
              {shownCode ? "קוד חדש" : "קישור טלפון"}
            </button>
          </p>
        </>
      )}

      {isPending ? null : isError ? (
        <NoConnection />
      ) : data.length === 0 ? (
        <p className={ui.muted}>אין טלפון מקושר.</p>
      ) : (
        <div className={ui.flushTable}>
          <table>
            <thead>
              <tr>
                <th>מכשיר</th>
                <th>קושר</th>
                <th>שימוש אחרון</th>
                <th className={ui.rowAction}>
                  <span className="visually-hidden">ניתוק</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((phone) => (
                <tr key={phone.id}>
                  <td title={phone.user_agent}>
                    {deviceName(phone.user_agent)}
                  </td>
                  <td>{formatDate(phone.linked_at)}</td>
                  <td>{formatDate(phone.last_used_at)}</td>
                  <td className={ui.rowAction}>
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
        </div>
      )}
    </section>
  );
}

/** Whether a phone that wasn't linked when the code was issued is in the
 * list now: the customer has used the code. */
function codeUsed(
  phones: LinkedPhone[] | undefined,
  linkedBefore: Set<number>,
): boolean {
  return phones?.some((phone) => !linkedBefore.has(phone.id)) ?? false;
}

/** A rough name from the browser's user agent, enough for staff to tell
 * two phones apart. The full text is in the cell's tooltip. */
function deviceName(userAgent: string): string {
  if (/iPhone/.test(userAgent)) return "iPhone";
  if (/iPad/.test(userAgent)) return "iPad";
  if (/Android/.test(userAgent)) return "Android";
  return "מכשיר אחר";
}
