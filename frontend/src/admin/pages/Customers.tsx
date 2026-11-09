// The customer list: searched, filtered, sorted and paged on the server
// (decision 0037), each active customer with a check-in button. The
// filters live in the address (?q=&came_in=&sort=&page=&inactive=1), so
// coming back from a customer's page keeps them. The search box sends what
// was typed after a short pause.
import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../backend/client";
import {
  CAME_IN_LABELS,
  CUSTOMER_LIST_KEY,
  SORT_LABELS,
  formatDate,
  formatPhone,
  formatTime,
  type CameIn,
  type SortBy,
} from "../customers";
import { PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { CheckInButton } from "./CheckInDialog";
import { NoConnection } from "../../shared/NoConnection";
import styles from "./Customers.module.css";

// How long the search box waits after the last key before searching.
const SEARCH_DELAY_MS = 300;

type Filters = {
  q: string;
  came_in: CameIn;
  sort: SortBy;
  page: number;
  inactive: boolean;
};

// Bad values in the address (a hand-edited link) fall back to the
// defaults rather than asking the server for something it refuses.
function readFilters(params: URLSearchParams): Filters {
  const cameIn = params.get("came_in");
  const sort = params.get("sort");
  const page = Number(params.get("page"));
  return {
    q: params.get("q") ?? "",
    came_in: cameIn && cameIn in CAME_IN_LABELS ? (cameIn as CameIn) : "any",
    sort: sort && sort in SORT_LABELS ? (sort as SortBy) : "name",
    page: Number.isSafeInteger(page) && page > 1 ? page : 1,
    inactive: params.get("inactive") === "1",
  };
}

function toParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.came_in !== "any") params.set("came_in", filters.came_in);
  if (filters.sort !== "name") params.set("sort", filters.sort);
  if (filters.page > 1) params.set("page", String(filters.page));
  if (filters.inactive) params.set("inactive", "1");
  return params;
}

async function fetchCustomers(filters: Filters) {
  const { data, response } = await api.GET("/api/customers", {
    params: {
      query: {
        active: !filters.inactive,
        q: filters.q || undefined,
        came_in: filters.came_in,
        sort: filters.sort,
        page: filters.page,
      },
    },
  });
  if (data) return data;
  throw new Error(`GET /api/customers failed: ${response.status}`);
}

export function Customers() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const { data, isPending, isError, isPlaceholderData } = useQuery({
    queryKey: [...CUSTOMER_LIST_KEY, filters],
    queryFn: () => fetchCustomers(filters),
    // The last page stays on screen while the next one loads, so typing
    // doesn't flash an empty list.
    placeholderData: keepPreviousData,
  });

  /** A new search or filter starts again from page 1. Typing replaces the
   * history entry, so Back doesn't step through every letter. */
  function change(next: Partial<Filters>, { replace = false } = {}) {
    setParams(toParams({ ...filters, page: 1, ...next }), { replace });
  }

  const filtered = filters.q !== "" || filters.came_in !== "any";

  return (
    <>
      <PageHead
        title={filters.inactive ? "לקוחות לא פעילים" : "לקוחות"}
        actions={
          <Link className={ui.primaryLink} to="/customers/new">
            לקוח חדש
          </Link>
        }
      />
      <div className={`${ui.panel} ${styles.filters}`}>
        <SearchBox
          value={filters.q}
          onSearch={(q) => change({ q }, { replace: true })}
        />
        <div className={ui.field}>
          <label htmlFor="customers-came-in">הגיעו</label>
          <select
            id="customers-came-in"
            value={filters.came_in}
            onChange={(event) =>
              change({ came_in: event.target.value as CameIn })
            }
          >
            {Object.entries(CAME_IN_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className={ui.field}>
          <label htmlFor="customers-sort">מיון</label>
          <select
            id="customers-sort"
            value={filters.sort}
            onChange={(event) => change({ sort: event.target.value as SortBy })}
          >
            {Object.entries(SORT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <label className={styles.inactive}>
          <input
            type="checkbox"
            checked={filters.inactive}
            onChange={(event) => change({ inactive: event.target.checked })}
          />{" "}
          לקוחות לא פעילים
        </label>
      </div>
      {isPending ? null : isError && !data ? (
        <NoConnection />
      ) : data.customers.length === 0 ? (
        <div className={ui.tablePanel}>
          <p className={ui.empty}>
            {filtered
              ? "אין לקוחות שמתאימים לחיפוש."
              : filters.inactive
                ? "אין לקוחות לא פעילים."
                : 'עדיין אין לקוחות. מוסיפים לקוח בכפתור "לקוח חדש".'}
          </p>
        </div>
      ) : (
        <>
          <div
            className={`${ui.tablePanel} ${isPlaceholderData ? styles.loading : ""}`}
          >
            <table>
              <thead>
                <tr>
                  <th>שם</th>
                  <th>טלפון</th>
                  <th>כניסה אחרונה</th>
                  {!filters.inactive && (
                    <th className={ui.rowAction}>
                      <span className="visually-hidden">כניסה</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {data.customers.map((customer) => (
                  <Row
                    key={customer.id}
                    customer={customer}
                    canCheckIn={!filters.inactive}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            page={data.page}
            pageCount={data.page_count}
            total={data.total}
            onPage={(page) => change({ page })}
          />
        </>
      )}
    </>
  );
}

function Row({
  customer,
  canCheckIn,
}: {
  customer: Schemas["CustomerListRow"];
  canCheckIn: boolean;
}) {
  const name = `${customer.first_name} ${customer.last_name}`;
  return (
    <tr>
      <td>
        <Link className={ui.rowLink} to={`/customers/${customer.id}`}>
          {name}
        </Link>
      </td>
      <td className={ui.muted}>
        <span dir="ltr">{formatPhone(customer.phone)}</span>
      </td>
      <td className={styles.when}>
        {customer.last_check_in_at ? (
          <>
            {formatDate(customer.last_check_in_at)}{" "}
            <span className={ui.muted}>
              {formatTime(customer.last_check_in_at)}
            </span>
          </>
        ) : (
          <span className={ui.muted}>אף פעם</span>
        )}
      </td>
      {canCheckIn && (
        <td className={ui.rowAction}>
          <CheckInButton customerId={customer.id} name={name} />
        </td>
      )}
    </tr>
  );
}

/** The search box. It keeps what's typed itself and sends it after a
 * pause; a new address (Back, a link) puts that address's search in it. */
function SearchBox({
  value,
  onSearch,
}: {
  value: string;
  onSearch: (q: string) => void;
}) {
  const [text, setText] = useState(value);
  // The address's search the box last agreed with. When the address moves
  // on its own, the box follows; when it moves because of what was typed,
  // the box keeps any letters typed since.
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    setSynced(value);
    setText(value);
  }

  useEffect(() => {
    if (text === synced) return;
    const timer = setTimeout(() => {
      setSynced(text);
      onSearch(text);
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, synced, onSearch]);

  return (
    <div className={`${ui.field} ${styles.search}`}>
      <label htmlFor="customers-search">חיפוש</label>
      <input
        id="customers-search"
        type="search"
        placeholder="שם או טלפון"
        autoComplete="off"
        maxLength={100}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
    </div>
  );
}

function Pager({
  page,
  pageCount,
  total,
  onPage,
}: {
  page: number;
  pageCount: number;
  total: number;
  onPage: (page: number) => void;
}) {
  return (
    <nav className={styles.pager} aria-label="עמודים">
      <span className={ui.muted}>
        {total === 1 ? "לקוח אחד" : `${total} לקוחות`}
      </span>
      {pageCount > 1 && (
        <span className={styles.pages}>
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            הקודם
          </button>
          <span>
            עמוד {page} מתוך {pageCount}
          </span>
          <button
            type="button"
            disabled={page >= pageCount}
            onClick={() => onPage(page + 1)}
          >
            הבא
          </button>
        </span>
      )}
    </nav>
  );
}
