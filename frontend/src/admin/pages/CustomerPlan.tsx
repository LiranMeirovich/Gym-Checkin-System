// The Plan section of a customer's page: what covers this month, the
// manager's choice for a month with no plan, changing or clearing this
// month's choice, and every choice so far. The price comes from the
// server; the forms only send the plan and which month or choice
// they showed.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDate, planKey, type Customer } from "../customers";
import { isManager } from "../roles";
import { PLAN_NAMES, formatMonth, formatShekels, type Plan } from "../prices";
import { useSession } from "../session";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
} from "../../shared/NoConnection";
import ui from "../layout/ui.module.css";
import { StatusBadge } from "../../shared/Status";
import styles from "./CustomerPlan.module.css";

type PlanStatus = Schemas["PlanStatus"];
type PlanChoice = Schemas["PlanChoiceRow"];
type PlanOption = Schemas["PlanOption"];

const PRICE_NOT_SET = "המחיר למסלול הזה לא נקבע. יש להזין אותו במסך המחירים.";
const CUSTOMER_INACTIVE = "הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.";

const REFUSALS: Record<string, string> = {
  month_not_choosable: "החודש התחלף מאז שהדף נפתח. רעננו את הדף.",
  price_not_set: PRICE_NOT_SET,
  month_covered: "לחודש הזה כבר יש מסלול.",
  customer_inactive: CUSTOMER_INACTIVE,
};

const CORRECTION_REFUSALS: Record<string, string> = {
  not_correctable: "אפשר לשנות רק מסלול שהתחיל בחודש הנוכחי.",
  price_not_set: PRICE_NOT_SET,
  no_change: "זה כבר המסלול והמחיר של החודש.",
  choice_replaced: "המסלול כבר שונה מאז שהדף נפתח. מוצג המצב העדכני.",
  month_covered: "המסלול החדש חופף לחודש שכבר יש לו מסלול.",
  customer_inactive: CUSTOMER_INACTIVE,
};

// Refusals after which the page was out of date: show what's there now.
const STALE = new Set(["month_covered", "choice_replaced"]);

export async function fetchPlan(id: number): Promise<PlanStatus> {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/plan",
    {
      params: { path: { customer_id: id } },
    },
  );
  if (data) return data;
  throw new Error(`GET /api/customers/${id}/plan failed: ${response.status}`);
}

export function CustomerPlan({ customer }: { customer: Customer }) {
  const session = useSession();
  // Kept here, not in the forms: a refusal can refresh the section and
  // swap the form, and the message must outlive that.
  const [message, setMessage] = useState<string | null>(null);
  const { data, isPending, isError } = useQuery({
    queryKey: planKey(customer.id),
    queryFn: () => fetchPlan(customer.id),
  });

  if (isPending) return null;
  if (isError) {
    return (
      <section className={ui.panel}>
        <h2>מסלול</h2>
        <NoConnection />
      </section>
    );
  }
  const canManage = customer.active && isManager(session);
  const covering = data.covering;
  return (
    <section className={ui.panel}>
      <h2>מסלול לחודש {formatMonth(data.current_month)}</h2>
      {message && <p role="alert">{message}</p>}
      <div className={ui.statusLine}>
        {covering ? (
          <>
            <StatusBadge tone="ok">יש מסלול</StatusBadge>
            <strong>{describe(covering)}</strong>
          </>
        ) : (
          <>
            <StatusBadge tone="warn">אין מסלול</StatusBadge>
            <span className={ui.muted}>אין מסלול לחודש הזה.</span>
          </>
        )}
      </div>
      {canManage && !covering && (
        <ChooseForm
          customerId={customer.id}
          month={data.current_month}
          options={data.options}
          onMessage={setMessage}
        />
      )}
      {canManage &&
        covering &&
        (data.correctable ? (
          <CorrectForm
            // A new covering choice starts a fresh form.
            key={covering.id}
            customerId={customer.id}
            choice={covering}
            options={data.options}
            onMessage={setMessage}
          />
        ) : (
          <p className={ui.note}>
            המסלול התחיל ב־{formatMonth(covering.start_month)}, ולכן אי אפשר
            לשנות אותו.
          </p>
        ))}
      <History choices={data.history} />
    </section>
  );
}

/** "שלושה חודשים, ₪650, עד 01/2027". */
export function describe(choice: PlanChoice): string {
  if (choice.plan === null || choice.unit_price_agorot === null) {
    return "ללא מסלול";
  }
  const price = formatShekels(choice.unit_price_agorot);
  switch (choice.plan) {
    case "single_entry":
      return `${PLAN_NAMES.single_entry}, ${price} לכל כניסה`;
    case "tri_monthly":
      return `${PLAN_NAMES.tri_monthly}, ${price}, עד ${formatMonth(choice.end_month)}`;
    case "monthly":
      return `${PLAN_NAMES.monthly}, ${price}`;
  }
}

type Answer = {
  data?: PlanStatus;
  error?: { error?: string } | object;
};

/** Sends a plan request and handles the answer the same way for every form:
 * new status into the cache, or a refusal message. Returns whether it
 * saved. */
function useSave(
  customerId: number,
  refusals: Record<string, string>,
  onMessage: (message: string | null) => void,
) {
  const queryClient = useQueryClient();
  const [sending, setSending] = useState(false);

  async function save(send: () => Promise<Answer>): Promise<boolean> {
    setSending(true);
    onMessage(null);
    try {
      const { data, error } = await send();
      if (data) {
        queryClient.setQueryData(planKey(customerId), data);
        return true;
      }
      const code =
        error && "error" in error && typeof error.error === "string"
          ? error.error
          : undefined;
      onMessage((code && refusals[code]) || "השמירה נכשלה. נסו שוב.");
      if (code && STALE.has(code)) {
        void queryClient.invalidateQueries({ queryKey: planKey(customerId) });
      }
    } catch {
      onMessage(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
    return false;
  }

  return { save, sending };
}

function ChooseForm({
  customerId,
  month,
  options,
  onMessage,
}: {
  customerId: number;
  month: string;
  options: PlanOption[];
  onMessage: (message: string | null) => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const { save, sending } = useSave(customerId, REFUSALS, onMessage);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!plan) return;
    await save(() =>
      api.POST("/api/customers/{customer_id}/plan", {
        params: { path: { customer_id: customerId } },
        body: { plan, month },
      }),
    );
  }

  return (
    <form onSubmit={submit}>
      <PlanOptions
        legend={`בחירת מסלול לחודש ${formatMonth(month)}`}
        options={options}
        plan={plan}
        onChange={setPlan}
      />
      <button type="submit" disabled={sending || !plan}>
        שמירת המסלול
      </button>
    </form>
  );
}

function CorrectForm({
  customerId,
  choice,
  options,
  onMessage,
}: {
  customerId: number;
  choice: PlanChoice;
  options: PlanOption[];
  onMessage: (message: string | null) => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const { save, sending } = useSave(customerId, CORRECTION_REFUSALS, onMessage);

  function correct(to: Plan | null) {
    return save(() =>
      api.POST("/api/customers/{customer_id}/plan/corrections", {
        params: { path: { customer_id: customerId } },
        body: { replaces_id: choice.id, plan: to },
      }),
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (plan) await correct(plan);
  }

  return (
    <form onSubmit={submit} className={ui.subsection}>
      <PlanOptions
        legend="שינוי המסלול"
        options={options}
        plan={plan}
        onChange={setPlan}
      />
      {confirmingClear ? (
        <div className={ui.buttons}>
          <span>לבטל את המסלול? החודשים שהוא מכסה יישארו בלי מסלול.</span>
          <button
            type="button"
            className={styles.danger}
            disabled={sending}
            onClick={() => void correct(null)}
          >
            כן, לבטל
          </button>
          <button type="button" onClick={() => setConfirmingClear(false)}>
            לא
          </button>
        </div>
      ) : (
        <div className={ui.buttons}>
          <button type="submit" disabled={sending || !plan}>
            שינוי המסלול
          </button>
          <button
            type="button"
            disabled={sending}
            onClick={() => setConfirmingClear(true)}
          >
            ביטול המסלול
          </button>
        </div>
      )}
    </form>
  );
}

function PlanOptions({
  legend,
  options,
  plan,
  onChange,
}: {
  legend: string;
  options: PlanOption[];
  plan: Plan | null;
  onChange: (plan: Plan) => void;
}) {
  return (
    <fieldset>
      <legend>{legend}</legend>
      <div className={ui.choices}>
        {options.map((option) => (
          <label key={option.plan} className={ui.choice}>
            <input
              type="radio"
              name="plan"
              value={option.plan}
              checked={plan === option.plan}
              disabled={option.amount_agorot === null}
              onChange={() => onChange(option.plan)}
            />
            {PLAN_NAMES[option.plan]}
            <span className={ui.choicePrice}>
              {option.amount_agorot === null
                ? "המחיר לא נקבע"
                : formatShekels(option.amount_agorot)}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Whether a history row is in force, was replaced, or is a "no plan" row. */
function state(choice: PlanChoice): string {
  if (choice.plan === null) return "ביטול מסלול";
  if (choice.replaced_by_id !== null) return "הוחלף";
  return "בתוקף";
}

function History({ choices }: { choices: PlanChoice[] }) {
  if (choices.length === 0) return null;
  return (
    <div className={ui.subsection}>
      <h3>היסטוריית מסלולים</h3>
      <div className={ui.flushTable}>
        <table>
          <thead>
            <tr>
              <th>חודשים</th>
              <th>מסלול</th>
              <th>מחיר</th>
              <th>מצב</th>
              <th>נבחר על ידי</th>
              <th>תאריך</th>
            </tr>
          </thead>
          <tbody>
            {choices.map((choice) => (
              <tr key={choice.id}>
                <td>
                  {formatMonth(choice.start_month)}
                  {choice.end_month !== choice.start_month &&
                    ` עד ${formatMonth(choice.end_month)}`}
                </td>
                <td>
                  {choice.plan === null ? "ללא מסלול" : PLAN_NAMES[choice.plan]}
                </td>
                <td>
                  {choice.unit_price_agorot === null
                    ? "—"
                    : formatShekels(choice.unit_price_agorot)}
                </td>
                <td>{state(choice)}</td>
                <td>
                  {choice.chosen_by === "customer"
                    ? "הלקוח"
                    : (choice.staff_name ?? "צוות")}
                </td>
                <td>{formatDate(choice.chosen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
