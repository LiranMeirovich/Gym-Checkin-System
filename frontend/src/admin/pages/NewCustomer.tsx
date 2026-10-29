// Adding a customer. A phone that belongs to an inactive customer brings
// that customer back instead (decision 0023); one that belongs to an
// active customer links to them.
import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { api, type Schemas } from "../backend/client";
import {
  CUSTOMERS_KEY,
  FIELD_ERRORS,
  NOTES_MAX_LENGTH,
  customerKey,
  type CustomerField,
} from "../customers";

const EMPTY: Schemas["NewCustomer"] = {
  first_name: "",
  last_name: "",
  phone: "",
  date_of_birth: "",
  notes: "",
};

export function NewCustomer() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<CustomerField, string>>>(
    {},
  );
  const [takenBy, setTakenBy] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setFormError(null);
    setTakenBy(null);
    try {
      const { data, error, response } = await api.POST("/api/customers", {
        body: values,
      });
      if (data) {
        const { customer, reactivated } = data;
        queryClient.setQueryData(customerKey(customer.id), customer);
        void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
        navigate(`/customers/${customer.id}`, { state: { reactivated } });
        return;
      }
      setErrors({});
      if (response.status === 400 && error && "errors" in error) {
        const fields = Object.keys(error.errors) as CustomerField[];
        setErrors(Object.fromEntries(fields.map((f) => [f, FIELD_ERRORS[f]])));
      } else if (
        response.status === 409 &&
        error &&
        "customer_id" in error &&
        error.customer_id
      ) {
        setTakenBy(error.customer_id);
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

  function field(
    name: Exclude<CustomerField, "notes">,
    label: string,
    input: object = {},
  ) {
    return (
      <p>
        <label htmlFor={name}>{label}</label>{" "}
        <input
          id={name}
          value={values[name]}
          onChange={(event) =>
            setValues({ ...values, [name]: event.target.value })
          }
          required
          {...input}
        />{" "}
        {errors[name] && <span role="alert">{errors[name]}</span>}
      </p>
    );
  }

  return (
    <>
      <h1>לקוח חדש</h1>
      <p>
        <Link to="/customers">חזרה לרשימה</Link>
      </p>
      <form onSubmit={submit} autoComplete="off">
        {formError && <p role="alert">{formError}</p>}
        {takenBy !== null && (
          <p role="alert">
            המספר הזה כבר שייך ללקוח פעיל.{" "}
            <Link to={`/customers/${takenBy}`}>לכרטיס הלקוח</Link>
          </p>
        )}
        {field("first_name", "שם פרטי", { maxLength: 50 })}
        {field("last_name", "שם משפחה", { maxLength: 50 })}
        {field("phone", "טלפון", { type: "tel", dir: "ltr" })}
        {field("date_of_birth", "תאריך לידה", { type: "date" })}
        <p>
          <label htmlFor="notes">הערות (בלי פרטים רפואיים)</label>{" "}
          <textarea
            id="notes"
            value={values.notes}
            maxLength={NOTES_MAX_LENGTH}
            onChange={(event) =>
              setValues({ ...values, notes: event.target.value })
            }
          />{" "}
          {errors.notes && <span role="alert">{errors.notes}</span>}
        </p>
        <p>
          <button type="submit" disabled={sending}>
            הוספה
          </button>
        </p>
      </form>
    </>
  );
}
