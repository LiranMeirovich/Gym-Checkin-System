// The home screen: what's happening at the gym now (design doc: "Admin:
// dashboard"). Four lists, each from its own route so other screens can
// reuse them; the instructor at the desk is the one watching it, and
// spots a check-in or sign-up that doesn't match who's in the gym.
//
// Each list refreshes itself: today's check-ins every 15 seconds, the rest
// every minute (they change a few times a day). The first load counts as
// activity; every refresh after it is a background refresh
// (`refreshHeaders`), so a dashboard left open still locks on time.
// TanStack Query pauses the refreshes while the window is hidden.
import { useQuery, type QueryFunctionContext } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { NoConnection } from "../../shared/NoConnection";
import { StatusBadge } from "../../shared/Status";
import { api, refreshHeaders, type Schemas } from "../backend/client";
import { formatDate, formatPhone, formatTime } from "../customers";
import { PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { can } from "../roles";
import { useSession } from "../session";
import styles from "./Dashboard.module.css";

const CHECKINS_EVERY_MS = 15_000;
const LISTS_EVERY_MS = 60_000;

type Method = Schemas["TodaysCheckIn"]["method"];
type CustomerName = Schemas["CustomerName"];

const METHOD_NAMES: Record<Method, string> = {
  phone: "בטלפון",
  manual: "בדלפק",
};

function failed(path: string, response: Response): Error {
  return new Error(`GET ${path} failed: ${response.status}`);
}

async function fetchTodaysCheckins(context: QueryFunctionContext) {
  const path = "/api/checkins/today";
  const { data, response } = await api.GET(path, {
    headers: refreshHeaders(context),
  });
  if (data) return data.checkins;
  throw failed(path, response);
}

async function fetchNeedingNote(context: QueryFunctionContext) {
  const path = "/api/health-forms/needing-note";
  const { data, response } = await api.GET(path, {
    headers: refreshHeaders(context),
  });
  if (data) return data.forms;
  throw failed(path, response);
}

async function fetchExpiring(context: QueryFunctionContext) {
  const path = "/api/health-forms/expiring";
  const { data, response } = await api.GET(path, {
    headers: refreshHeaders(context),
  });
  if (data) return data.forms;
  throw failed(path, response);
}

async function fetchLatestCustomers(context: QueryFunctionContext) {
  const path = "/api/customers/latest";
  const { data, response } = await api.GET(path, {
    headers: refreshHeaders(context),
  });
  if (data) return data.customers;
  throw failed(path, response);
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
  const query = useQuery({
    queryKey: ["dashboard", "checkins-today"],
    queryFn: fetchTodaysCheckins,
    refetchInterval: CHECKINS_EVERY_MS,
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
                <th>איך</th>
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
                  <td className={ui.muted}>{METHOD_NAMES[checkin.method]}</td>
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
  const query = useQuery({
    queryKey: ["dashboard", "forms-needing-note"],
    queryFn: fetchNeedingNote,
    refetchInterval: LISTS_EVERY_MS,
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
  const query = useQuery({
    queryKey: ["dashboard", "forms-expiring"],
    queryFn: fetchExpiring,
    refetchInterval: LISTS_EVERY_MS,
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
  const query = useQuery({
    queryKey: ["dashboard", "latest-customers"],
    queryFn: fetchLatestCustomers,
    refetchInterval: LISTS_EVERY_MS,
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
