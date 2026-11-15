// The home screen: what's happening at the gym now (design doc: "Admin:
// dashboard"). Each list comes from its own route so other screens can
// reuse it; the instructor at the desk is the one watching it, and spots a
// check-in or sign-up that doesn't match who's in the gym. The manager also
// sees the health forms waiting for their review (decision 0041), and where
// last month's report stands (generated, emailed, approved, sent; red when
// an email failed).
//
// Each list refreshes itself: today's check-ins every 15 seconds, the rest
// every minute (they change a few times a day). Only the timed refreshes
// are background refreshes (`usePolledQuery`), so a dashboard left open
// still locks on time; they wait while the window is hidden.
import type { ReactNode } from "react";
import { Link } from "react-router";
import { NoConnection } from "../../shared/NoConnection";
import { formatMonth } from "../../shared/plans";
import { api, type Schemas } from "../backend/client";
import { formatDate, formatPhone, formatTime } from "../customers";
import { PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { usePolledQuery } from "../polling";
import { DeliveryBadge } from "../reportDelivery";
import { can } from "../roles";
import { useSession } from "../session";
import styles from "./Dashboard.module.css";

const CHECKINS_EVERY_MS = 15_000;
const LISTS_EVERY_MS = 60_000;

type CustomerName = Schemas["CustomerName"];

/** A list route's answer, picked out of its JSON; anything else throws. */
async function listOf<Answer, Row>(
  path: string,
  request: Promise<{ data?: Answer; response: Response }>,
  pick: (answer: Answer) => Row[],
): Promise<Row[]> {
  const { data, response } = await request;
  if (data) return pick(data);
  throw new Error(`GET ${path} failed: ${response.status}`);
}

export function Dashboard() {
  const session = useSession();
  const reviews = can(session, "health_forms.accept");
  const reports = can(session, "reports.manage");
  return (
    <>
      <PageHead title={`שלום, ${session.staff.display_name}`} />
      <div className={styles.grid}>
        <div className={styles.main}>
          <TodaysCheckins />
        </div>
        <div className={styles.side}>
          {reports && <ReportCard />}
          {reviews && <FormsToReview />}
          <LatestCustomers />
        </div>
      </div>
    </>
  );
}

/** A panel whose list loads and refreshes on its own. Keeps showing the
 * last answer if a refresh fails; says so only when there's nothing to
 * show. */
function ListPanel<T>({
  title,
  query,
  empty,
  children,
}: {
  title: ReactNode;
  query: { data: T[] | undefined; isPending: boolean; isError: boolean };
  empty: string;
  children: (rows: T[]) => ReactNode;
}) {
  const { data, isPending, isError } = query;
  return (
    <section className={ui.panel}>
      <h2 className={styles.title}>
        {title}
        {data && data.length > 0 && (
          <span className={styles.count}>{data.length}</span>
        )}
      </h2>
      {data ? (
        data.length === 0 ? (
          <p className={ui.muted}>{empty}</p>
        ) : (
          children(data)
        )
      ) : isPending ? null : isError ? (
        <NoConnection />
      ) : null}
    </section>
  );
}

function CustomerLink({ customer }: { customer: CustomerName }) {
  return (
    <Link className={ui.rowLink} to={`/customers/${customer.id}`}>
      {customer.first_name} {customer.last_name}
    </Link>
  );
}

function TodaysCheckins() {
  const path = "/api/checkins/today";
  const query = usePolledQuery({
    queryKey: ["dashboard", "checkins-today"],
    fetch: (headers) =>
      listOf(path, api.GET(path, { headers }), (answer) => answer.checkins),
    everyMs: CHECKINS_EVERY_MS,
  });
  return (
    <ListPanel title="כניסות היום" query={query} empty="עוד אין כניסות היום.">
      {(checkins) => (
        <div className={ui.flushTable}>
          <table>
            <thead>
              <tr>
                <th>שעה</th>
                <th>לקוח</th>
              </tr>
            </thead>
            <tbody>
              {checkins.map((checkin) => (
                <tr key={checkin.id}>
                  <td className={styles.time}>
                    {formatTime(checkin.checked_in_at)}
                  </td>
                  <td>
                    <CustomerLink customer={checkin.customer} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ListPanel>
  );
}

/** Forms with a "yes" the manager hasn't reviewed: they let the customer
 * in meanwhile. On the customer's page the manager opens the form, then
 * accepts it or adds a doctor's note; either takes it off this list. */
function FormsToReview() {
  const path = "/api/health-forms/needing-note";
  const query = usePolledQuery({
    queryKey: ["dashboard", "forms-to-review"],
    fetch: (headers) =>
      listOf(path, api.GET(path, { headers }), (answer) => answer.forms),
    everyMs: LISTS_EVERY_MS,
  });
  return (
    <ListPanel
      title="הצהרות לבדיקה"
      query={query}
      empty="אין הצהרות שממתינות לבדיקה."
    >
      {(forms) => (
        <>
          <p className={ui.muted}>
            סומן &quot;כן&quot; באחת השאלות. בכרטיס הלקוח אפשר לאשר את ההצהרה או
            להוסיף אישור רפואי.
          </p>
          <ul className={styles.list}>
            {forms.map((entry) => (
              <li key={entry.customer.id} className={styles.row}>
                <CustomerLink customer={entry.customer} />
                <span className={styles.detail}>
                  <span className={ui.muted}>
                    נחתמה {formatDate(entry.signed_on)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </ListPanel>
  );
}

/** Last month's report: the server says which month and where it stands.
 * Opens the Reports screen on that month. */
function ReportCard() {
  const query = usePolledQuery({
    queryKey: ["dashboard", "report"],
    fetch: async (headers) => {
      const { data, response } = await api.GET("/api/reports/latest", {
        headers,
      });
      if (data) return data;
      throw new Error(`GET /api/reports/latest failed: ${response.status}`);
    },
    everyMs: LISTS_EVERY_MS,
  });
  const { data } = query;
  return (
    <section className={ui.panel}>
      <h2 className={styles.title}>
        דוח חודשי{data && ` · ${formatMonth(data.month)}`}
      </h2>
      {data ? (
        <div className={styles.row}>
          <DeliveryBadge delivery={data.delivery} />
          <Link className={ui.rowLink} to={`/reports?month=${data.month}`}>
            למסך הדוחות
          </Link>
        </div>
      ) : query.isPending ? null : query.isError ? (
        <NoConnection />
      ) : null}
    </section>
  );
}

function LatestCustomers() {
  const path = "/api/customers/latest";
  const query = usePolledQuery({
    queryKey: ["dashboard", "latest-customers"],
    fetch: (headers) =>
      listOf(path, api.GET(path, { headers }), (answer) => answer.customers),
    everyMs: LISTS_EVERY_MS,
  });
  return (
    <ListPanel title="לקוחות חדשים" query={query} empty="עדיין אין לקוחות.">
      {(customers) => (
        <ul className={styles.list}>
          {customers.map((customer) => (
            <li key={customer.id} className={styles.row}>
              <CustomerLink customer={customer} />
              <span className={styles.detail}>
                <span dir="ltr" className={ui.muted}>
                  {formatPhone(customer.phone)}
                </span>
                <span className={ui.muted}>
                  {formatDate(customer.created_at)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </ListPanel>
  );
}
