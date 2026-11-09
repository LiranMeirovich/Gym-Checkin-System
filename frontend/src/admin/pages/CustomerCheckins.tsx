// The customer page's latest check-ins, newest first: the day and time
// (decision 0037). Who checked someone in at the desk is in the activity
// log, not here. A check-in from the dialog refreshes it.
import { useQuery } from "@tanstack/react-query";
import { api } from "../backend/client";
import {
  checkinsKey,
  formatDate,
  formatTime,
  type Customer,
} from "../customers";
import { NoConnection } from "../../shared/NoConnection";
import ui from "../layout/ui.module.css";

async function fetchCheckins(id: number) {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/checkins",
    { params: { path: { customer_id: id } } },
  );
  if (data) return data.checkins;
  throw new Error(
    `GET /api/customers/${id}/checkins failed: ${response.status}`,
  );
}

export function CustomerCheckins({ customer }: { customer: Customer }) {
  const { data, isPending, isError } = useQuery({
    queryKey: checkinsKey(customer.id),
    queryFn: () => fetchCheckins(customer.id),
  });

  return (
    <section className={ui.panel}>
      <h2>כניסות אחרונות</h2>
      {isPending ? null : isError ? (
        <NoConnection />
      ) : data.length === 0 ? (
        <p className={ui.muted}>עדיין אין כניסות.</p>
      ) : (
        <div className={ui.flushTable}>
          <table>
            <thead>
              <tr>
                <th>תאריך</th>
                <th>שעה</th>
              </tr>
            </thead>
            <tbody>
              {data.map((checkin) => (
                <tr key={checkin.id}>
                  <td>{formatDate(checkin.checked_in_at)}</td>
                  <td>{formatTime(checkin.checked_in_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
