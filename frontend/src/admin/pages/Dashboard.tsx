// The home screen: what's happening at the gym now (design doc: "Admin:
// dashboard"). Four lists, each from its own route so other screens can
// reuse them; the instructor at the desk is the one watching it, and
// spots a check-in or sign-up that doesn't match who's in the gym.
//
// Each list refreshes itself: today's check-ins every 15 seconds, the rest
// every minute (they change a few times a day). Only the timed refreshes
// are background refreshes (`usePolledQuery`), so a dashboard left open
// still locks on time; they wait while the window is hidden.
import type { ReactNode } from "react";
import { Link } from "react-router";
import { NoConnection } from "../../shared/NoConnection";
import { StatusBadge } from "../../shared/Status";
import { api, type Schemas } from "../backend/client";
import { formatDate, formatPhone, formatTime } from "../customers";
import { PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { usePolledQuery } from "../polling";
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
  const formsVisible = can(session, "health_forms.view_status");
  return (
    <>
      <PageHead title={`שלום, ${session.staff.display_name}`} />
      <div className={styles.grid}>
        <div className={styles.main}>
          <TodaysCheckins />
        </div>
        <div className={styles.side}>
          {formsVisible && <NeedingNote />}
          {formsVisible && <Expiring />}
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

function NeedingNote() {
  const path = "/api/health-forms/needing-note";
  const query = usePolledQuery({
    queryKey: ["dashboard", "forms-needing-note"],
    fetch: (headers) =>
      listOf(path, api.GET(path, { headers }), (answer) => answer.forms),
    everyMs: LISTS_EVERY_MS,
  });
  return (
    <ListPanel
      title="ממתינים לאישור רופא"
      query={query}
      empty="אין הצהרות שממתינות לאישור רופא."
    >
      {(forms) => (
        <ul className={styles.list}>
          {forms.map((entry) => (
            <li key={entry.customer.id} className={styles.row}>
              <CustomerLink customer={entry.customer} />
              <span className={styles.detail}>
                <StatusBadge tone="stop">אין כניסה</StatusBadge>
                <span className={ui.muted}>
                  נחתמה {formatDate(entry.signed_on)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </ListPanel>
  );
}

function Expiring() {
  const path = "/api/health-forms/expiring";
  const query = usePolledQuery({
    queryKey: ["dashboard", "forms-expiring"],
    fetch: (headers) =>
      listOf(path, api.GET(path, { headers }), (answer) => answer.forms),
    everyMs: LISTS_EVERY_MS,
  });
  return (
    <ListPanel
      title="הצהרות שפגות בקרוב"
      query={query}
      empty="אין הצהרות שפגות ב-30 הימים הקרובים."
    >
      {(forms) => (
        <ul className={styles.list}>
          {forms.map((entry) => (
            <li key={entry.customer.id} className={styles.row}>
              <CustomerLink customer={entry.customer} />
              <span className={styles.detail}>
                <StatusBadge tone="warn">
                  בתוקף עד {formatDate(entry.valid_until)}
                </StatusBadge>
              </span>
            </li>
          ))}
        </ul>
      )}
    </ListPanel>
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
