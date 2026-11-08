// The customer list: active customers by name, each with a check-in
// button, or the inactive ones.
// Search and sorting by recent check-ins come in milestone 4.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../backend/client";
import { CUSTOMER_LIST_KEY, formatPhone } from "../customers";
import { PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { CheckInButton } from "./CheckInDialog";
import { NoConnection } from "../../shared/NoConnection";

async function fetchCustomers(active: boolean) {
  const { data, response } = await api.GET("/api/customers", {
    params: { query: { active } },
  });
  if (data) return data.customers;
  throw new Error(`GET /api/customers failed: ${response.status}`);
}

export function Customers() {
  const [showInactive, setShowInactive] = useState(false);
  const { data, isPending, isError } = useQuery({
    queryKey: [...CUSTOMER_LIST_KEY, { active: !showInactive }],
    queryFn: () => fetchCustomers(!showInactive),
  });

  return (
    <>
      <PageHead
        title={showInactive ? "לקוחות לא פעילים" : "לקוחות"}
        actions={
          <>
            <label>
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(event) => setShowInactive(event.target.checked)}
              />{" "}
              הצגת לקוחות לא פעילים
            </label>
            <Link className={ui.primaryLink} to="/customers/new">
              לקוח חדש
            </Link>
          </>
        }
      />
      {isPending ? null : isError ? (
        <NoConnection />
      ) : data.length === 0 ? (
        <div className={ui.tablePanel}>
          <p className={ui.empty}>
            {showInactive
              ? "אין לקוחות לא פעילים."
              : 'עדיין אין לקוחות. מוסיפים לקוח בכפתור "לקוח חדש".'}
          </p>
        </div>
      ) : (
        <div className={ui.tablePanel}>
          <table>
            <thead>
              <tr>
                <th>שם</th>
                <th>טלפון</th>
                {!showInactive && (
                  <th className={ui.rowAction}>
                    <span className="visually-hidden">כניסה</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {data.map((customer) => (
                <tr key={customer.id}>
                  <td>
                    <Link
                      className={ui.rowLink}
                      to={`/customers/${customer.id}`}
                    >
                      {customer.first_name} {customer.last_name}
                    </Link>
                  </td>
                  <td className={ui.muted}>
                    <span dir="ltr">{formatPhone(customer.phone)}</span>
                  </td>
                  {!showInactive && (
                    <td className={ui.rowAction}>
                      <CheckInButton
                        customerId={customer.id}
                        name={`${customer.first_name} ${customer.last_name}`}
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
