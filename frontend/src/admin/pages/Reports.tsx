// The monthly report, for the owner and managers (reports.manage; design
// doc: "Monthly report"). Opens on last month; the month list, the rows and
// the totals all come from the server (app/core/reports.py), which also
// decides which months can be opened. Generating runs on the server after
// it answers, so the screen asks again every few seconds until it's done.
// Hiding the screen is never the protection: the server checks the
// permission on every route.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api, type Schemas } from "../backend/client";
import { formatDate, formatTime } from "../customers";
import { PageHead, Panel } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { usePolledQuery } from "../polling";
import { NoConnection } from "../../shared/NoConnection";
import { PLAN_NAMES, formatMonth, formatShekels } from "../../shared/plans";
import styles from "./Reports.module.css";

type Report = Schemas["ReportAnswer"];
type Refused = Schemas["ReportRefused"];

const MONTHS_KEY = ["reports"] as const;
function reportKey(month: string) {
  return ["reports", month] as const;
}

// While a generation runs.
const POLL_MS = 2000;

/** The server refused the screen: this role can't manage reports. */
class Forbidden extends Error {}

async function fetchMonths(): Promise<string[]> {
  const { data, response } = await api.GET("/api/reports");
  if (data) return data.months;
  if (response.status === 403) throw new Forbidden();
  throw new Error(`GET /api/reports failed: ${response.status}`);
}

const REFUSALS: Record<Refused["error"], string> = {
  month_not_finished: "אפשר להפיק דוח רק לחודש שהסתיים.",
  already_generating: "הדוח של החודש הזה כבר בהפקה.",
};
const FAILED = "הפקת הדוח לא הצליחה. נסו שוב.";
const NO_CONNECTION = "אין חיבור לשרת. נסו שוב.";

export function Reports() {
  const months = useQuery({
    queryKey: MONTHS_KEY,
    queryFn: fetchMonths,
    // No retries: a refusal won't change, and each request counts as
    // activity for the auto-lock.
    retry: false,
  });
  const [params, setParams] = useSearchParams();

  if (months.error instanceof Forbidden) {
    return (
      <>
        <PageHead title="דוח חודשי" />
        <p role="alert">הדוחות פתוחים למנהלים בלבד.</p>
      </>
    );
  }
  if (months.isPending) return <PageHead title="דוח חודשי" />;
  if (months.isError) {
    return (
      <>
        <PageHead title="דוח חודשי" />
        <NoConnection />
      </>
    );
  }

  const wanted = params.get("month");
  const month =
    wanted && months.data.includes(wanted) ? wanted : months.data[0];
  // The server always offers at least last month.
  if (month === undefined) return <PageHead title="דוח חודשי" />;
  return (
    <MonthReport
      key={month}
      month={month}
      months={months.data}
      onPick={(picked) => setParams({ month: picked })}
    />
  );
}

function MonthReport({
  month,
  months,
  onPick,
}: {
  month: string;
  months: string[];
  onPick: (month: string) => void;
}) {
  const queryClient = useQueryClient();
  const report = usePolledQuery({
    queryKey: reportKey(month),
    fetch: async (headers) => {
      const { data, response } = await api.GET("/api/reports/{month}", {
        params: { path: { month } },
        headers,
      });
      if (data) return data;
      throw new Error(`GET /api/reports/${month} failed: ${response.status}`);
    },
    everyMs: (data) => (data?.generating ? POLL_MS : false),
  });
  // The generation the screen started, by the one it replaces: when the
  // server stops generating and still shows that one, it failed.
  const [waitingToReplace, setWaitingToReplace] = useState<
    string | null | undefined
  >(undefined);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const data = report.data;
  const failed =
    data !== undefined &&
    waitingToReplace !== undefined &&
    !data.generating &&
    data.generated_at === waitingToReplace;

  async function generate() {
    if (!data) return;
    setSending(true);
    setError(null);
    try {
      const { data: answer, error: refused } = await api.POST(
        "/api/reports/{month}/generate",
        { params: { path: { month } } },
      );
      if (answer) {
        setWaitingToReplace(data.generated_at);
        queryClient.setQueryData(reportKey(month), answer);
      } else if (refused && "error" in refused) {
        setError(REFUSALS[refused.error]);
      } else {
        setError(FAILED);
      }
    } catch {
      setError(NO_CONNECTION);
    } finally {
      setSending(false);
    }
  }

  const generating = sending || data?.generating === true;
  return (
    <>
      <PageHead
        title="דוח חודשי"
        actions={
          <>
            <label htmlFor="report-month" className={ui.muted}>
              חודש
            </label>
            <select
              id="report-month"
              value={month}
              onChange={(event) => onPick(event.target.value)}
            >
              {months.map((option) => (
                <option key={option} value={option}>
                  {formatMonth(option)}
                </option>
              ))}
            </select>
          </>
        }
      />
      {report.isPending ? null : report.isError || !data ? (
        <NoConnection />
      ) : (
        <>
          <Panel>
            <div className={ui.statusLine}>
              <span>
                <Status report={data} generating={generating} />
              </span>
            </div>
            <div className={ui.buttons}>
              <button
                type="button"
                className={ui.primary}
                disabled={generating}
                onClick={() => void generate()}
              >
                {data.generated_at ? "הפקה מחדש" : "הפקת הדוח"}
              </button>
              {data.files && !generating && (
                <>
                  <a
                    className={styles.download}
                    href={`/api/reports/${month}/excel`}
                    download
                  >
                    הורדת Excel
                  </a>
                  <a
                    className={styles.download}
                    href={`/api/reports/${month}/pdf`}
                    download
                  >
                    הורדת PDF
                  </a>
                </>
              )}
            </div>
            {(error ?? (failed ? FAILED : null)) && (
              <p role="alert" className={ui.note}>
                {error ?? FAILED}
              </p>
            )}
          </Panel>
          {data.generated_at && <Rows report={data} />}
        </>
      )}
    </>
  );
}

function Status({
  report,
  generating,
}: {
  report: Report;
  generating: boolean;
}) {
  if (generating) return <>הדוח בהפקה…</>;
  if (!report.generated_at) {
    return <span className={ui.muted}>הדוח לחודש הזה עדיין לא הופק.</span>;
  }
  return (
    <>
      הופק ב־
      <span dir="ltr">
        {formatDate(report.generated_at)} {formatTime(report.generated_at)}
      </span>
      {report.generated_by ? ` על ידי ${report.generated_by}` : " אוטומטית"}
    </>
  );
}

function Rows({ report }: { report: Report }) {
  if (report.rows.length === 0) {
    return (
      <div className={ui.tablePanel}>
        <p className={ui.empty}>אין בחודש הזה לקוחות עם מנוי או כרטיסייה.</p>
      </div>
    );
  }
  return (
    <div className={ui.tablePanel}>
      <table>
        <thead>
          <tr>
            <th>שם פרטי</th>
            <th>שם משפחה</th>
            <th>מנוי</th>
            <th>תשלום</th>
            <th>סיום מנוי</th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row, index) => (
            <tr key={index}>
              <td>{row.first_name}</td>
              <td>{row.last_name}</td>
              <td>{row.plans.map((plan) => PLAN_NAMES[plan]).join(" + ")}</td>
              <td>
                <span dir="ltr">{formatShekels(row.payment_agorot)}</span>
              </td>
              <td>
                {row.ends_on && (
                  <span dir="ltr">{formatDate(row.ends_on)}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className={styles.total}>
            <td colSpan={3}>סה"כ</td>
            <td>
              <span dir="ltr">{formatShekels(report.total_agorot)}</span>
            </td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
