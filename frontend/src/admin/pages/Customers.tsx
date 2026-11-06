// The customer list: active customers by name, each with a check-in
// button, or the inactive ones.
// Search and sorting by recent check-ins come in milestone 4.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../backend/client";
import { CUSTOMER_LIST_KEY, formatPhone } from "../customers";
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
      <h1>{showInactive ? "לקוחות לא פעילים" : "לקוחות"}</h1>
      <p>
        <Link to="/customers/new">לקוח חדש</Link>{" "}
        <label>
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
          />{" "}
          הצגת לקוחות לא פעילים
        </label>
      </p>
      {isPending ? null : isError ? (
        <NoConnection />
      ) : data.length === 0 ? (
        <p>אין לקוחות להצגה.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>שם</th>
              <th>טלפון</th>
              {!showInactive && <th />}
            </tr>
          </thead>
          <tbody>
            {data.map((customer) => (
              <tr key={customer.id}>
                <td>
                  <Link to={`/customers/${customer.id}`}>
                    {customer.first_name} {customer.last_name}
                  </Link>
                </td>
                <td dir="ltr">{formatPhone(customer.phone)}</td>
                {!showInactive && (
                  <td>
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
      )}
    </>
  );
}
