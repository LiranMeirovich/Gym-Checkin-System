// Checking in, once the phone is linked and its health form is valid
// (design doc: "Check-in flow"). The check-in is sent as soon as this
// step shows, so one scan of the wall QR is enough. If no plan covers the
// month, the plan page shows this customer's prices; tapping one chooses
// it and checks in, in the same request.
//
// The server decides everything: a refusal for the health form sends the
// page back to the form, a 401 back to the link form.
import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDay } from "../../shared/dates";
import {
  PLAN_NAMES,
  formatMonth,
  formatShekels,
  type Plan,
} from "../../shared/plans";
import { formatTime, lastDayOf } from "../times";
import { StatusBadge } from "../../shared/Status";
import styles from "./Phone.module.css";

type CheckedIn = Schemas["CheckedIn"];
type PlanRequired = Schemas["PlanRequired"];
type HealthFormStatus = Schemas["HealthFormStatus"];

type Answer =
  | { kind: "checked_in"; answer: CheckedIn }
  | { kind: "plan_required"; answer: PlanRequired }
  | { kind: "price_not_set" }
  | { kind: "health_form_required"; status: HealthFormStatus }
  | { kind: "not_linked" };

async function sendCheckIn(plan: Plan | null): Promise<Answer> {
  const { data, error, response } = await api.POST("/api/check-in", {
    body: plan === null ? {} : { plan },
  });
  if (data) return { kind: "checked_in", answer: data };
  if (response.status === 401) return { kind: "not_linked" };
  if (response.status === 409 && error && "detail" in error) {
    switch (error.detail) {
      case "plan_required":
        return { kind: "plan_required", answer: error };
      case "price_not_set":
        return { kind: "price_not_set" };
      case "health_form_required":
        return { kind: "health_form_required", status: error.health_form };
    }
  }
  throw new Error(`POST /api/check-in failed: ${response.status}`);
}

type Props = {
  firstName: string;
  // The last day of the customer's health form, shown with the check-in.
  formValidUntil: string | null;
  // The server says the form isn't valid after all (it expired, say).
  onHealthFormRequired: (status: HealthFormStatus) => void;
  // The phone's link is gone.
  onNotLinked: () => void;
};

export function CheckInStep({
  firstName,
  formValidUntil,
  onHealthFormRequired,
  onNotLinked,
}: Props) {
  const [priceGone, setPriceGone] = useState(false);
  const checkIn = useMutation({
    mutationFn: sendCheckIn,
    onSuccess: (result) => {
      if (result.kind === "health_form_required") {
        onHealthFormRequired(result.status);
      } else if (result.kind === "not_linked") {
        onNotLinked();
      } else if (result.kind === "price_not_set") {
        // Ask again: the answer has the plans with their current prices.
        setPriceGone(true);
        checkIn.mutate(null);
      }
    },
  });

  // Once per visit to the page. React's development double-run of effects
  // keeps this ref, so it doesn't send a second check-in.
  const sent = useRef(false);
  const { mutate } = checkIn;
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    mutate(null);
  }, [mutate]);

  if (checkIn.isError) {
    return (
      <>
        <h1 className={styles.heading}>שלום, {firstName}</h1>
        <p role="alert">אין חיבור לשרת.</p>
        <button
          type="button"
          className={styles.wide}
          onClick={() => checkIn.mutate(null)}
        >
          לנסות שוב
        </button>
      </>
    );
  }
  const result = checkIn.data;
  if (checkIn.isPending || result === undefined) {
    return <p className={styles.waiting}>רושמים כניסה…</p>;
  }
  if (result.kind === "checked_in") {
    return (
      <CheckedInPage
        firstName={firstName}
        answer={result.answer}
        formValidUntil={formValidUntil}
      />
    );
  }
  if (result.kind === "plan_required") {
    return (
      <PlanPage
        firstName={firstName}
        answer={result.answer}
        priceGone={priceGone}
        onChoose={(plan) => {
          setPriceGone(false);
          checkIn.mutate(plan);
        }}
      />
    );
  }
  // The other answers hand over to CheckIn (the form, or the link form).
  return null;
}

function CheckedInPage({
  firstName,
  answer,
  formValidUntil,
}: {
  firstName: string;
  answer: CheckedIn;
  formValidUntil: string | null;
}) {
  const time = formatTime(answer.checked_in_at);
  return (
    <>
      {answer.outcome === "checked_in" ? (
        <div role="status" className={styles.bell}>
          <h1 className={styles.bellGreeting}>שלום, {firstName}</h1>
          <p className={styles.bellWord}>אימון טוב!</p>
          <p className={styles.bellTime}>
            הכניסה נרשמה בשעה <bdi>{time}</bdi>
          </p>
        </div>
      ) : (
        <div role="status" className={styles.bellRepeat}>
          <h1 className={styles.bellGreeting}>שלום, {firstName}</h1>
          <p className={styles.bellWord}>כבר נרשמת</p>
          <p className={styles.bellTime}>
            בשעה <bdi>{time}</bdi>. אין צורך להירשם שוב.
          </p>
        </div>
      )}
      <ul className={styles.facts}>
        {answer.plan && (
          <li>
            <StatusBadge tone="ok">מסלול</StatusBadge>
            {planLine(answer.plan)}
          </li>
        )}
        {formValidUntil && (
          <li>
            <StatusBadge tone="ok">הצהרת בריאות</StatusBadge>
            בתוקף עד <bdi>{formatDay(formValidUntil)}</bdi>
          </li>
        )}
      </ul>
    </>
  );
}

/** What covers this month, in one line. */
function planLine(plan: Schemas["CoveringPlan"]): string {
  switch (plan.plan) {
    case "monthly":
      return `מסלול חודשי ל־${formatMonth(plan.start_month)}.`;
    case "tri_monthly":
      return `מסלול שלושה חודשים, בתוקף עד ${lastDayOf(plan.end_month)}.`;
    case "single_entry":
      return `כניסה בודדת: כל כניסה החודש נספרת בנפרד.`;
  }
}

function PlanPage({
  firstName,
  answer,
  priceGone,
  onChoose,
}: {
  firstName: string;
  answer: PlanRequired;
  priceGone: boolean;
  onChoose: (plan: Plan) => void;
}) {
  const month = formatMonth(answer.month);
  const anyPrice = answer.options.some((o) => o.price_agorot !== null);
  return (
    <>
      <p className={styles.lead}>שלום, {firstName}</p>
      <h1 className={styles.heading}>בחירת מסלול ל־{month}</h1>
      {priceGone && <p role="alert">המחיר של המסלול שנבחר השתנה. בחרו שוב.</p>}
      {anyPrice ? (
        <p>
          זו הכניסה הראשונה החודש. בחירת מסלול רושמת את הכניסה, והמסלול נקבע
          לחודש הזה. לשינוי אחר כך יש לפנות למנהל/ת.
        </p>
      ) : (
        <p role="alert">
          אי אפשר לבחור מסלול כרגע. פנו לצוות בדלפק, והם ירשמו את הכניסה.
        </p>
      )}
      <ul className={styles.plans}>
        {answer.options.map((option) => (
          <li key={option.plan}>
            <button
              type="button"
              className={styles.plan}
              disabled={option.price_agorot === null}
              onClick={() => onChoose(option.plan)}
            >
              <span className={styles.planName}>{PLAN_NAMES[option.plan]}</span>
              <span className={styles.planPrice}>
                {option.price_agorot === null
                  ? "המחיר עדיין לא נקבע"
                  : priceText(option.plan, option.price_agorot, answer.month)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

/** "₪250 לחודש 11/2026", and so on. */
function priceText(plan: Plan, agorot: number, month: string): string {
  const price = formatShekels(agorot);
  switch (plan) {
    case "monthly":
      return `${price} לחודש ${formatMonth(month)}`;
    case "tri_monthly":
      return `${price} לשלושה חודשים, מ־${formatMonth(month)}`;
    case "single_entry":
      return `${price} לכל כניסה החודש`;
  }
}
