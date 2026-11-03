// The Plan section of a customer's page: what covers this month, the
// manager's choice for a month with no plan, and every choice so far.
// The price and age group come from the server; the form only sends the
// plan and the month it showed.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDate, isManager, type Customer } from "../customers";
import {
  AGE_GROUP_NAMES,
  PLAN_NAMES,
  formatMonth,
  formatShekels,
  type Plan,
} from "../prices";
import { useSession } from "../session";

type PlanStatus = Schemas["PlanStatus"];
type PlanChoice = Schemas["PlanChoiceRow"];
type PlanOption = Schemas["PlanOption"];

// Under the customer's own key, so anything refreshing the customer
// refreshes their plan too.
function planKey(id: number) {
  return ["customers", id, "plan"] as const;
}

const REFUSALS: Record<string, string> = {
  month_not_choosable: "החודש התחלף מאז שהדף נפתח. רעננו את הדף.",
  price_not_set: "המחיר למסלול הזה לא נקבע. יש להזין אותו במסך המחירים.",
  month_covered: "לחודש הזה כבר יש מסלול.",
  customer_inactive: "הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.",
};

async function fetchPlan(id: number): Promise<PlanStatus> {
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
  const { data, isPending, isError } = useQuery({
    queryKey: planKey(customer.id),
    queryFn: () => fetchPlan(customer.id),
  });

  if (isPending) return null;
  if (isError) {
    return (
      <section>
        <h2>מסלול</h2>
        <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>
      </section>
    );
  }
  return (
    <section>
      <h2>מסלול לחודש {formatMonth(data.current_month)}</h2>
      {data.covering ? (
        <p>{describe(data.covering)}</p>
      ) : (
        <p>אין מסלול לחודש הזה.</p>
      )}
      {!data.covering && customer.active && isManager(session) && (
        <ChooseForm
          customerId={customer.id}
          month={data.current_month}
          options={data.options}
        />
      )}
      <History choices={data.history} />
    </section>
  );
}

/** "שלושה חודשים, ₪650, עד 01/2027". */
function describe(choice: PlanChoice): string {
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

function ChooseForm({
  customerId,
  month,
  options,
}: {
  customerId: number;
  month: string;
  options: PlanOption[];
}) {
  const queryClient = useQueryClient();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!plan) return;
    setSending(true);
    try {
      const { data, error } = await api.POST(
        "/api/customers/{customer_id}/plan",
        {
          params: { path: { customer_id: customerId } },
          body: { plan, month },
        },
      );
      if (data) {
        queryClient.setQueryData(planKey(customerId), data);
        return;
      }
      const code = error && "error" in error ? error.error : undefined;
      setMessage((code && REFUSALS[code]) || "השמירה נכשלה. נסו שוב.");
      // Someone else may have chosen meanwhile; show what's there now.
      if (code === "month_covered") {
        void queryClient.invalidateQueries({ queryKey: planKey(customerId) });
      }
    } catch {
      setMessage("אין חיבור לשרת. נסו שוב.");
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit}>
      {message && <p role="alert">{message}</p>}
      <fieldset>
        <legend>בחירת מסלול לחודש {formatMonth(month)}</legend>
        {options.map((option) => (
          <p key={option.plan}>
            <label>
              <input
                type="radio"
                name="plan"
                value={option.plan}
                checked={plan === option.plan}
                disabled={option.amount_agorot === null}
                onChange={() => setPlan(option.plan)}
              />{" "}
              {PLAN_NAMES[option.plan]} ({AGE_GROUP_NAMES[option.age_group]}):{" "}
              {option.amount_agorot === null
                ? "המחיר לא נקבע"
                : formatShekels(option.amount_agorot)}
            </label>
          </p>
        ))}
      </fieldset>
      <p>
        <button type="submit" disabled={sending || !plan}>
          שמירת המסלול
        </button>
      </p>
    </form>
  );
}

function History({ choices }: { choices: PlanChoice[] }) {
  if (choices.length === 0) return null;
  return (
    <>
      <h3>היסטוריית מסלולים</h3>
      <table>
        <thead>
          <tr>
            <th>חודשים</th>
            <th>מסלול</th>
            <th>מחיר</th>
            <th>קבוצת גיל</th>
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
              <td>{PLAN_NAMES[choice.plan]}</td>
              <td>{formatShekels(choice.unit_price_agorot)}</td>
              <td>{AGE_GROUP_NAMES[choice.age_group]}</td>
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
    </>
  );
}
