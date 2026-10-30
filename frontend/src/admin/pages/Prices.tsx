// The price table: what's in effect this month, upcoming changes and the
// full history, for all staff. The manager also gets the change form. Hiding
// the form is never the protection: the server checks `prices.edit`.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type Schemas } from "../backend/client";
import { formatDate, isManager } from "../customers";
import {
  AGE_GROUPS,
  AGE_GROUP_NAMES,
  PLANS,
  PLAN_NAMES,
  formatMonth,
  formatShekels,
  priceField,
  shekelsToAgorot,
} from "../prices";
import { useSession } from "../session";

const PRICES_KEY = ["prices"] as const;

type Overview = Schemas["PriceOverview"];

async function fetchPrices() {
  const { data, response } = await api.GET("/api/prices");
  if (data) return data;
  throw new Error(`GET /api/prices failed: ${response.status}`);
}

export function Prices() {
  const session = useSession();
  const { data, isPending, isError } = useQuery({
    queryKey: PRICES_KEY,
    queryFn: fetchPrices,
  });

  return (
    <>
      <h1>מחירון</h1>
      <p>
        <Link to="/">חזרה</Link>
      </p>
      {isPending ? null : isError ? (
        <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>
      ) : (
        <>
          <Current overview={data} />
          <Rows title="שינויים עתידיים" rows={data.upcoming} empty="אין." />
          {isManager(session) && <ChangeForm overview={data} />}
          <Rows
            title="היסטוריה"
            rows={data.history}
            empty="עדיין אין מחירים."
          />
        </>
      )}
    </>
  );
}

function Current({ overview }: { overview: Overview }) {
  function cell(plan: string, ageGroup: string) {
    const price = overview.current.find(
      (c) => c.plan === plan && c.age_group === ageGroup,
    );
    if (price?.amount_agorot == null || !price.valid_from_month) {
      return "לא נקבע";
    }
    return (
      <>
        <span dir="ltr">{formatShekels(price.amount_agorot)}</span> (מ-
        <span dir="ltr">{formatMonth(price.valid_from_month)}</span>)
      </>
    );
  }

  return (
    <>
      <h2>
        המחירים החודש (
        <span dir="ltr">{formatMonth(overview.current_month)}</span>)
      </h2>
      <table>
        <thead>
          <tr>
            <th>תוכנית</th>
            {AGE_GROUPS.map((group) => (
              <th key={group}>{AGE_GROUP_NAMES[group]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PLANS.map((plan) => (
            <tr key={plan}>
              <td>{PLAN_NAMES[plan]}</td>
              {AGE_GROUPS.map((group) => (
                <td key={group}>{cell(plan, group)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Rows({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: Schemas["PriceRow"][];
  empty: string;
}) {
  return (
    <>
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <p>{empty}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>תוכנית</th>
              <th>גיל</th>
              <th>מחיר</th>
              <th>בתוקף מ-</th>
              <th>הוזן בתאריך</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{PLAN_NAMES[row.plan]}</td>
                <td>{AGE_GROUP_NAMES[row.age_group]}</td>
                <td dir="ltr">{formatShekels(row.amount_agorot)}</td>
                <td dir="ltr">{formatMonth(row.valid_from_month)}</td>
                <td dir="ltr">{formatDate(row.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function ChangeForm({ overview }: { overview: Overview }) {
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(overview.current_month);
  // Only the prices typed in are sent; an empty box leaves that price alone.
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setOutcome(null);

    const prices: Schemas["PriceChange"][] = [];
    const notAmounts = new Set<string>();
    for (const plan of PLANS) {
      for (const age_group of AGE_GROUPS) {
        const name = priceField(plan, age_group);
        const text = amounts[name]?.trim();
        if (!text) continue;
        const amount_agorot = shekelsToAgorot(text);
        if (amount_agorot === null) notAmounts.add(name);
        else prices.push({ plan, age_group, amount_agorot });
      }
    }
    setErrors(notAmounts);
    if (notAmounts.size > 0) return;
    if (prices.length === 0) {
      setFormError("לא הוזן אף מחיר.");
      return;
    }

    setSending(true);
    try {
      const { data, error, response } = await api.POST("/api/prices", {
        body: { valid_from_month: month, prices },
      });
      if (data) {
        queryClient.setQueryData(PRICES_KEY, data);
        setAmounts({});
        // An amount already in effect for that month adds no row.
        setOutcome(
          data.history.length > overview.history.length
            ? "נשמר."
            : "לא נוסף דבר: המחירים האלה כבר בתוקף באותו חודש.",
        );
      } else if (response.status === 400 && error && "errors" in error) {
        setErrors(new Set(Object.keys(error.errors)));
      } else {
        setFormError("השמירה נכשלה. נסו שוב.");
      }
    } catch {
      // No answer at all; everything typed stays, to send again.
      setFormError("אין חיבור לשרת. נסו שוב.");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <h2>שינוי מחירים</h2>
      <p>
        מחיר חדש חל מהחודש שנבחר ואילך, ושינויים עתידיים שכבר נקבעו נשארים.
        לקוחות שכבר בחרו תוכנית שומרים על המחיר שבחרו בו.
      </p>
      <form onSubmit={submit} autoComplete="off">
        {formError && <p role="alert">{formError}</p>}
        {outcome && <p role="status">{outcome}</p>}
        <p>
          <label htmlFor="valid_from_month">בתוקף מחודש</label>{" "}
          <input
            id="valid_from_month"
            type="month"
            dir="ltr"
            value={month}
            min={overview.current_month}
            onChange={(event) => setMonth(event.target.value)}
            required
          />{" "}
          {errors.has("valid_from_month") && (
            <span role="alert">החודש הנוכחי או עד 24 חודשים קדימה</span>
          )}
        </p>
        <table>
          <thead>
            <tr>
              <th>תוכנית</th>
              {AGE_GROUPS.map((group) => (
                <th key={group}>{AGE_GROUP_NAMES[group]} (₪)</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PLANS.map((plan) => (
              <tr key={plan}>
                <td>{PLAN_NAMES[plan]}</td>
                {AGE_GROUPS.map((group) => {
                  const name = priceField(plan, group);
                  return (
                    <td key={group}>
                      <input
                        aria-label={`${PLAN_NAMES[plan]}, ${AGE_GROUP_NAMES[group]}`}
                        inputMode="decimal"
                        dir="ltr"
                        value={amounts[name] ?? ""}
                        onChange={(event) =>
                          setAmounts({ ...amounts, [name]: event.target.value })
                        }
                      />{" "}
                      {errors.has(name) && (
                        <span role="alert">
                          סכום בין ₪0.01 ל-₪10,000, עד שתי ספרות אחרי הנקודה
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          <button type="submit" disabled={sending}>
            שמירה
          </button>
        </p>
      </form>
    </>
  );
}
