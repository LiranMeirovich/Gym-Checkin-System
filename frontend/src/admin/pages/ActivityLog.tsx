// The activity log: what staff changed, newest first, for the manager
// (activity_log.view; decisions 0021, 0037). The filters live in the
// address (?staff_id=&from=&to=&target_type=&target_id=), so a filtered log
// can be linked to and survives a reload. "More" loads the next, older
// page.
import { useState, type FormEvent } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { api } from "../backend/client";
import {
  TARGET_NAMES,
  actionName,
  changesOf,
  fieldName,
  formatValue,
  isLtr,
  targetName,
  type LogEntry,
} from "../activityLog";
import { formatDate, formatTime } from "../customers";
import { PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { NoConnection } from "../../shared/NoConnection";
import styles from "./ActivityLog.module.css";

type Filters = {
  staff_id?: number;
  from?: string;
  to?: string;
  target_type?: string;
  target_id?: number;
};

const FILTER_KEYS = [
  "staff_id",
  "from",
  "to",
  "target_type",
  "target_id",
] as const;

class Forbidden extends Error {}
// The server refused the filters (a hand-edited or old link): 400 for
// filters that can't be used together, 422 for a malformed value.
class BadFilter extends Error {}

function readFilters(params: URLSearchParams): Filters {
  const id = (key: string) => {
    const value = Number(params.get(key));
    return Number.isInteger(value) && value > 0 ? value : undefined;
  };
  const date = (key: string) => {
    const value = params.get(key);
    return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : undefined;
  };
  // Passed on as they are: which combinations work is the server's rule,
  // and a refusal shows as a bad filter.
  return {
    staff_id: id("staff_id"),
    from: date("from"),
    to: date("to"),
    target_type: params.get("target_type") || undefined,
    target_id: id("target_id"),
  };
}

async function fetchPage(filters: Filters, beforeId: number | undefined) {
  const { data, response } = await api.GET("/api/activity-log", {
    params: { query: { ...filters, before_id: beforeId } },
  });
  if (data) return data;
  if (response.status === 403) throw new Forbidden();
  if (response.status === 400 || response.status === 422) throw new BadFilter();
  throw new Error(`GET /api/activity-log failed: ${response.status}`);
}

async function fetchStaff() {
  const { data, response } = await api.GET("/api/staff");
  if (data) return data.staff;
  throw new Error(`GET /api/staff failed: ${response.status}`);
}

export function ActivityLog() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const log = useInfiniteQuery({
    queryKey: ["activity-log", filters],
    queryFn: ({ pageParam }) => fetchPage(filters, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (page) => page.next_before_id ?? undefined,
    retry: (count, error) =>
      !(error instanceof Forbidden || error instanceof BadFilter) && count < 3,
  });

  if (log.error instanceof Forbidden) {
    return (
      <>
        <PageHead title="יומן פעולות" />
        <p role="alert">היומן פתוח למנהלים בלבד.</p>
      </>
    );
  }

  const entries = log.data?.pages.flatMap((page) => page.entries) ?? [];
  const filtered = FILTER_KEYS.some((key) => filters[key] !== undefined);

  return (
    <>
      <PageHead title="יומן פעולות" />
      <FilterForm
        // A new address (a link, Back) starts the form from it again.
        key={params.toString()}
        filters={filters}
        onApply={(next) => setParams(toParams(next))}
      />
      {log.isPending ? null : log.error instanceof BadFilter ? (
        <p role="alert">
          הסינון בכתובת לא תקין. <Link to="/activity-log">לכל היומן</Link>
        </p>
      ) : !log.data ? (
        // Nothing loaded at all. A failed "more" or background refresh
        // keeps the rows already on screen (below).
        <NoConnection />
      ) : entries.length === 0 ? (
        <div className={ui.tablePanel}>
          <p className={ui.empty}>
            {filtered
              ? "אין פעולות שמתאימות לסינון."
              : "אין עדיין פעולות ביומן."}
          </p>
        </div>
      ) : (
        <>
          <div className={ui.tablePanel}>
            <table className={styles.log}>
              <thead>
                <tr>
                  <th>מתי</th>
                  <th>מי</th>
                  <th>פעולה</th>
                  <th>על מה</th>
                  <th>שינוי</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <Row key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
          {log.hasNextPage && (
            <div className={ui.buttons}>
              <button
                type="button"
                disabled={log.isFetchingNextPage}
                onClick={() => void log.fetchNextPage()}
              >
                {log.isFetchingNextPage ? "טוען…" : "פעולות קודמות"}
              </button>
            </div>
          )}
          {log.isFetchNextPageError && <NoConnection />}
        </>
      )}
    </>
  );
}

function toParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params;
}

function FilterForm({
  filters,
  onApply,
}: {
  filters: Filters;
  onApply: (filters: Filters) => void;
}) {
  // No retries: a refusal won't change, and each request counts as
  // activity for the auto-lock.
  const staff = useQuery({
    queryKey: ["staff"],
    queryFn: fetchStaff,
    retry: false,
  });
  const [staffId, setStaffId] = useState(String(filters.staff_id ?? ""));
  const [from, setFrom] = useState(filters.from ?? "");
  const [to, setTo] = useState(filters.to ?? "");
  const [targetType, setTargetType] = useState(filters.target_type ?? "");
  const [targetId, setTargetId] = useState(String(filters.target_id ?? ""));

  function submit(event: FormEvent) {
    event.preventDefault();
    onApply({
      staff_id: staffId ? Number(staffId) : undefined,
      from: from || undefined,
      to: to || undefined,
      target_type: targetType || undefined,
      target_id: targetType && targetId ? Number(targetId) : undefined,
    });
  }

  return (
    <form className={`${ui.panel} ${styles.filters}`} onSubmit={submit}>
      <div className={ui.field}>
        <label htmlFor="log-staff">איש צוות</label>
        <select
          id="log-staff"
          value={staffId}
          onChange={(event) => setStaffId(event.target.value)}
        >
          <option value="">כולם</option>
          {staff.data?.map((member) => (
            <option key={member.id} value={member.id}>
              {member.display_name}
              {member.active ? "" : " (לא פעיל/ה)"}
            </option>
          ))}
          {/* A filter from the address that isn't in the list (or the
              list didn't load) still shows what is filtered. */}
          {staffId &&
            !staff.data?.some((member) => String(member.id) === staffId) && (
              <option value={staffId}>#{staffId}</option>
            )}
        </select>
        {staff.isError && (
          <span role="alert">רשימת הצוות לא נטענה. נסו לרענן את הדף.</span>
        )}
      </div>
      <div className={ui.field}>
        <label htmlFor="log-from">מתאריך</label>
        <input
          id="log-from"
          type="date"
          value={from}
          max={to || undefined}
          onChange={(event) => setFrom(event.target.value)}
        />
      </div>
      <div className={ui.field}>
        <label htmlFor="log-to">עד תאריך</label>
        <input
          id="log-to"
          type="date"
          value={to}
          min={from || undefined}
          onChange={(event) => setTo(event.target.value)}
        />
      </div>
      <div className={ui.field}>
        <label htmlFor="log-target">על מה</label>
        <select
          id="log-target"
          value={targetType}
          onChange={(event) => setTargetType(event.target.value)}
        >
          <option value="">הכול</option>
          {Object.entries(TARGET_NAMES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
          {/* An old or unknown target type from the address: shown by its
              stored name rather than as "everything". */}
          {targetType && !(targetType in TARGET_NAMES) && (
            <option value={targetType}>{targetType}</option>
          )}
        </select>
      </div>
      {targetType && targetType !== "settings" && (
        <div className={ui.field}>
          <label htmlFor="log-target-id">מספר</label>
          <input
            id="log-target-id"
            type="number"
            inputMode="numeric"
            min={1}
            dir="ltr"
            className={styles.targetId}
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
          />
        </div>
      )}
      <div className={styles.filterButtons}>
        <button type="submit" className={ui.primary}>
          סינון
        </button>
        <Link to="/activity-log">ניקוי</Link>
      </div>
    </form>
  );
}

function Row({ entry }: { entry: LogEntry }) {
  const changes = changesOf(entry);
  return (
    <tr>
      <td className={styles.when}>
        {formatDate(entry.at)}{" "}
        <span className={ui.muted}>{formatTime(entry.at)}</span>
      </td>
      <td>{entry.staff.display_name}</td>
      <td>{actionName(entry.action)}</td>
      <td>
        <Target entry={entry} />
      </td>
      <td>
        {changes.length === 0 ? (
          <span className={ui.muted}>—</span>
        ) : (
          <ul className={styles.changes}>
            {changes.map((change) => (
              <li key={change.field}>
                <span className={styles.field}>{fieldName(change.field)}:</span>{" "}
                {change.hasBefore && (
                  <Value field={change.field} value={change.before} old />
                )}
                {change.hasBefore && change.hasAfter && " ← "}
                {change.hasAfter && (
                  <Value field={change.field} value={change.after} />
                )}
              </li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

function Target({ entry }: { entry: LogEntry }) {
  const kind = targetName(entry.target_type);
  if (entry.target_id === null) return <>{kind}</>;
  const label = entry.target_name ?? <span dir="ltr">#{entry.target_id}</span>;
  return (
    <>
      <span className={ui.muted}>{kind}:</span>{" "}
      {entry.target_type === "customer" ? (
        <Link to={`/customers/${entry.target_id}`}>{label}</Link>
      ) : (
        label
      )}
    </>
  );
}

function Value({
  field,
  value,
  old = false,
}: {
  field: string;
  value: unknown;
  old?: boolean;
}) {
  const className = old ? styles.old : undefined;
  if (field === "customer_id" && typeof value === "number") {
    return (
      <Link className={className} to={`/customers/${value}`}>
        <span dir="ltr">#{value}</span>
      </Link>
    );
  }
  const text = formatValue(field, value);
  return isLtr(field) ? (
    <span className={className} dir="ltr">
      {text}
    </span>
  ) : (
    <span className={className}>{text}</span>
  );
}
