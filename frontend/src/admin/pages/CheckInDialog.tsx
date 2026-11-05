// Manual check-in at the desk (design doc: "Manual check-in"; decisions
// 0004, 0017, 0032), from the customer list and the customer's page.
//
// The dialog shows only what check-in needs (decision 0023): the name,
// whether the health form is valid, and this month's plan. It reads them
// from GET .../health-form and GET .../plan; POST .../check-in decides
// again on the server, in the same order as the phone. With no plan this
// month, the manager picks one; an instructor's check-in records single
// entry (decision 0017). No valid health form, no check-in (decision 0004).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type Schemas } from "../backend/client";
import { formatTime, healthFormKey, isManager, planKey } from "../customers";
import { PLAN_NAMES, formatMonth, formatShekels, type Plan } from "../prices";
import { useSession } from "../session";
import { fetchStatus } from "./CustomerHealthForm";
import { describe, fetchPlan } from "./CustomerPlan";

type CheckedIn = Schemas["CheckedIn"];
type PlanOption = Schemas["PlanOption"];

const NO_CONNECTION = "אין חיבור לשרת. נסו שוב.";
const PRICE_NOT_SET = "המחיר לא נקבע. יש להזין אותו במסך המחירים.";

type Props = {
  customerId: number;
  name: string;
};

/** A "Check in" button that opens the dialog. */
export function CheckInButton({ customerId, name }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        רישום כניסה
      </button>
      {open && (
        <CheckInDialog
          customerId={customerId}
          name={name}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function CheckInDialog({
  customerId,
  name,
  onClose,
}: Props & { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    // Escape closes a modal dialog; onClose tells React.
    <dialog ref={ref} onClose={onClose}>
      <h2>רישום כניסה: {name}</h2>
      <CheckInBody customerId={customerId} />
      <p>
        <button type="button" onClick={() => ref.current?.close()}>
          סגירה
        </button>
      </p>
    </dialog>
  );
}

function CheckInBody({ customerId }: { customerId: number }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const manager = isManager(session);
  const health = useQuery({
    queryKey: healthFormKey(customerId),
    queryFn: () => fetchStatus(customerId),
  });
  const plan = useQuery({
    queryKey: planKey(customerId),
    queryFn: () => fetchPlan(customerId),
  });
  const [picked, setPicked] = useState<Plan | null>(null);
  const [result, setResult] = useState<CheckedIn | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  if (health.isPending || plan.isPending) return null;
  if (health.isError || plan.isError) {
    return <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>;
  }

  async function checkIn() {
    setMessage(null);
    setSending(true);
    try {
      const { data, error, response } = await api.POST(
        "/api/customers/{customer_id}/check-in",
        {
          params: { path: { customer_id: customerId } },
          body: manager && picked ? { plan: picked } : {},
        },
      );
      if (data) {
        setResult(data);
        // A check-in can choose this month's plan (single entry, or the
        // manager's pick).
        void queryClient.invalidateQueries({ queryKey: planKey(customerId) });
        return;
      }
      if (response.status === 409 && error && "error" in error) {
        switch (error.error) {
          case "health_form_required":
            // Shown in place of the button: the form's status changed.
            queryClient.setQueryData(
              healthFormKey(customerId),
              error.health_form,
            );
            return;
          case "plan_required":
            // A plan was cleared since the dialog opened: pick one.
            void queryClient.invalidateQueries({
              queryKey: planKey(customerId),
            });
            setMessage("אין מסלול לחודש הזה. יש לבחור מסלול.");
            return;
          case "price_not_set":
            setMessage(PRICE_NOT_SET);
            return;
          case "customer_inactive":
            setMessage("הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.");
            return;
        }
      }
      setMessage(
        response.status === 403
          ? "אין הרשאה לבחור מסלול."
          : "הרישום נכשל. נסו שוב.",
      );
    } catch {
      setMessage(NO_CONNECTION);
    } finally {
      setSending(false);
    }
  }

  if (result) {
    const at = formatTime(result.checked_in_at);
    return (
      <p role="status">
        {result.outcome === "checked_in"
          ? `הכניסה נרשמה בשעה ${at}.`
          : `הלקוח כבר נרשם בשעה ${at}, לפני פחות מ-10 דקות. לא נרשמה כניסה נוספת.`}
        {result.plan && ` מסלול: ${PLAN_NAMES[result.plan.plan]}.`}
      </p>
    );
  }

  const formValid = health.data.state === "valid";
  const covering = plan.data.covering;
  const singleEntry = plan.data.options.find(
    (option) => option.plan === "single_entry",
  );

  let action: ReactNode;
  if (!formValid) {
    action = (
      <p role="alert">
        אין כניסה בלי הצהרת בריאות בתוקף.{" "}
        {health.data.state === "missing" ? (
          <Link to={`/customers/${customerId}/health-form`}>
            מילוי ההצהרה כאן, במחשב
          </Link>
        ) : (
          <Link to={`/customers/${customerId}`}>
            הוספת אישור רפואי בכרטיס הלקוח
          </Link>
        )}
      </p>
    );
  } else if (covering) {
    action = <CheckInSubmit sending={sending} onClick={checkIn} />;
  } else if (manager) {
    action = (
      <PlanPicker
        options={plan.data.options}
        picked={picked}
        onPick={setPicked}
        sending={sending}
        onSubmit={checkIn}
      />
    );
  } else if (singleEntry?.amount_agorot == null) {
    action = <p role="alert">{PRICE_NOT_SET}</p>;
  } else {
    action = (
      <>
        <p>
          אין מסלול לחודש הזה: תירשם {PLAN_NAMES.single_entry} (
          {formatShekels(singleEntry.amount_agorot)}).
        </p>
        <CheckInSubmit sending={sending} onClick={checkIn} />
      </>
    );
  }

  return (
    <>
      <p>
        הצהרת בריאות: {formValid ? "בתוקף" : "לא בתוקף"}
        <br />
        מסלול לחודש {formatMonth(plan.data.current_month)}:{" "}
        {covering ? describe(covering) : "אין"}
      </p>
      {message && <p role="alert">{message}</p>}
      {action}
    </>
  );
}

function CheckInSubmit({
  sending,
  disabled = false,
  onClick,
}: {
  sending: boolean;
  disabled?: boolean;
  onClick: () => Promise<void>;
}) {
  return (
    <p>
      <button
        type="button"
        disabled={sending || disabled}
        onClick={() => void onClick()}
      >
        אישור כניסה
      </button>
    </p>
  );
}

/** The manager's pick for a month with no plan, at this customer's price.
 * A plan without a price can't be picked. */
function PlanPicker({
  options,
  picked,
  onPick,
  sending,
  onSubmit,
}: {
  options: PlanOption[];
  picked: Plan | null;
  onPick: (plan: Plan) => void;
  sending: boolean;
  onSubmit: () => Promise<void>;
}) {
  return (
    <>
      <fieldset>
        <legend>אין מסלול לחודש הזה. בחירת מסלול:</legend>
        {options.map((option) => (
          <p key={option.plan}>
            <label>
              <input
                type="radio"
                name="check-in-plan"
                checked={picked === option.plan}
                disabled={option.amount_agorot === null}
                onChange={() => onPick(option.plan)}
              />{" "}
              {PLAN_NAMES[option.plan]}{" "}
              {option.amount_agorot === null
                ? "(המחיר לא נקבע)"
                : formatShekels(option.amount_agorot)}
            </label>
          </p>
        ))}
      </fieldset>
      <CheckInSubmit
        sending={sending}
        disabled={picked === null}
        onClick={onSubmit}
      />
    </>
  );
}
