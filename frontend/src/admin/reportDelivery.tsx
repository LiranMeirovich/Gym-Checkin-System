// Where a month's report stands, as the Reports screen and the dashboard's
// report card show it (design doc: "Monthly report"). The stage, which
// email failed and who did what all come from the server
// (app/core/report_delivery.py); this only words them.
import { StatusBadge, type Tone } from "../shared/Status";
import type { Schemas } from "./backend/client";

export type Delivery = Schemas["ReportDeliveryAnswer"];

const STAGE_NAMES: Record<Delivery["stage"], string> = {
  not_generated: "טרם הופק",
  generated: "הופק",
  emailed: "נשלח למנהל",
  approved: "אושר",
  sent: "נשלח לנמענים",
};

const FAILED_NAMES: Record<NonNullable<Delivery["failed_email"]>, string> = {
  manager_email: "השליחה למנהל נכשלה",
  recipients_email: "השליחה לנמענים נכשלה",
};

/** The stage as a badge: red when an email failed, green once it reached
 * the recipients, amber while it waits on something. */
export function DeliveryBadge({ delivery }: { delivery: Delivery }) {
  if (delivery.sending)
    return <StatusBadge tone="warn">נשלח עכשיו…</StatusBadge>;
  if (delivery.failed_email) {
    return (
      <StatusBadge tone="stop">
        {FAILED_NAMES[delivery.failed_email]}
      </StatusBadge>
    );
  }
  const tone: Tone = delivery.stage === "sent" ? "ok" : "warn";
  return <StatusBadge tone={tone}>{STAGE_NAMES[delivery.stage]}</StatusBadge>;
}
