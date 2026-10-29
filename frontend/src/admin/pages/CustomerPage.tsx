// One customer's page: their details, editing name, phone and notes, and
// the manager's date-of-birth change and deactivation. An inactive
// customer is read-only until reactivated. Linked phones, the health form
// and plans join this page in later features.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router";
import { api } from "../backend/client";
import {
  CUSTOMERS_KEY,
  FIELD_ERRORS,
  NOTES_MAX_LENGTH,
  customerKey,
  formatDate,
  formatPhone,
  isManager,
  type Customer,
  type CustomerField,
} from "../customers";
import { useSession } from "../session";

type Errors = Partial<Record<CustomerField, string>>;

/** What a save answered, for the form that sent it. */
type Outcome =
  | { saved: true }
  | { saved: false; errors?: Errors; takenBy?: number; message?: string };

async function fetchCustomer(id: number): Promise<Customer | null> {
  const { data, response } = await api.GET("/api/customers/{customer_id}", {
    params: { path: { customer_id: id } },
  });
  if (data) return data;
  if (response.status === 404 || response.status === 422) return null;
  throw new Error(`GET /api/customers/${id} failed: ${response.status}`);
}

export function CustomerPage() {
  const id = Number(useParams().id);
  const {
    data: customer,
    isPending,
    isError,
  } = useQuery({
    queryKey: customerKey(id),
    queryFn: () => fetchCustomer(id),
  });

  if (isPending) return null;
  if (isError) return <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>;
  if (!customer) {
    return (
      <>
        <p>הלקוח לא נמצא.</p>
        <p>
          <Link to="/customers">חזרה לרשימה</Link>
        </p>
      </>
    );
  }
  return <CustomerDetails customer={customer} />;
}

function CustomerDetails({ customer }: { customer: Customer }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const reactivated = useLocation().state?.reactivated === true;
  const [editing, setEditing] = useState(false);
  const manager = isManager(session);

  /** Send a change; on success the page shows the stored customer. */
  async function save(
    send: () => Promise<{
      data?: Customer;
      error?: unknown;
      response: Response;
    }>,
  ): Promise<Outcome> {
    try {
      const { data, error, response } = await send();
      if (data) {
        queryClient.setQueryData(customerKey(data.id), data);
        void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
        return { saved: true };
      }
      return refusal(response.status, error);
    } catch {
      return { saved: false, message: "אין חיבור לשרת. נסו שוב." };
    }
  }

  const path = { params: { path: { customer_id: customer.id } } };

  return (
    <>
      <h1>
        {customer.first_name} {customer.last_name}
        {!customer.active && " (לא פעיל/ה)"}
      </h1>
      <p>
        <Link to="/customers">חזרה לרשימה</Link>
      </p>
      {reactivated && (
        <p role="status">
          המספר היה שייך ללקוח לא פעיל, והוא הופעל מחדש עם הפרטים השמורים שלו.
          אפשר לעדכן אותם כאן.
        </p>
      )}

      {editing ? (
        <EditForm
          customer={customer}
          onSave={(body) =>
            save(() =>
              api.PATCH("/api/customers/{customer_id}", { ...path, body }),
            )
          }
          onDone={() => setEditing(false)}
        />
      ) : (
        <dl>
          <dt>טלפון</dt>
          <dd dir="ltr">{formatPhone(customer.phone)}</dd>
          <dt>תאריך לידה</dt>
          <dd>{formatDate(customer.date_of_birth)}</dd>
          <dt>הערות</dt>
          <dd style={{ whiteSpace: "pre-line" }}>{customer.notes || "—"}</dd>
          <dt>נוסף/ה</dt>
          <dd>{formatDate(customer.created_at)}</dd>
        </dl>
      )}

      {customer.active && !editing && (
        <p>
          <button type="button" onClick={() => setEditing(true)}>
            עריכת פרטים
          </button>
        </p>
      )}

      {customer.active && manager && !editing && (
        <DateOfBirthForm
          customer={customer}
          onSave={(date_of_birth) =>
            save(() =>
              api.PUT("/api/customers/{customer_id}/date-of-birth", {
                ...path,
                body: { date_of_birth },
              }),
            )
          }
        />
      )}

      {!editing && (customer.active ? manager : true) && (
        <ActiveToggle
          active={customer.active}
          onToggle={() =>
            save(() =>
              customer.active
                ? api.POST("/api/customers/{customer_id}/deactivate", path)
                : api.POST("/api/customers/{customer_id}/reactivate", path),
            )
          }
        />
      )}
    </>
  );
}

function refusal(status: number, error: unknown): Outcome {
  if (
    status === 400 &&
    error &&
    typeof error === "object" &&
    "errors" in error
  ) {
    const fields = Object.keys(error.errors as object) as CustomerField[];
    return {
      saved: false,
      errors: Object.fromEntries(fields.map((f) => [f, FIELD_ERRORS[f]])),
    };
  }
  if (
    status === 409 &&
    error &&
    typeof error === "object" &&
    "error" in error
  ) {
    if (error.error === "phone_taken" && "customer_id" in error) {
      return { saved: false, takenBy: error.customer_id as number };
    }
    return {
      saved: false,
      message: "הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.",
    };
  }
  return { saved: false, message: "השמירה נכשלה. נסו שוב." };
}

function OutcomeMessage({ outcome }: { outcome: Outcome | null }) {
  if (!outcome || outcome.saved) return null;
  if (outcome.takenBy !== undefined) {
    return (
      <p role="alert">
        המספר הזה כבר שייך ללקוח אחר.{" "}
        <Link to={`/customers/${outcome.takenBy}`}>לכרטיס הלקוח</Link>
      </p>
    );
  }
  return outcome.message ? <p role="alert">{outcome.message}</p> : null;
}

function EditForm({
  customer,
  onSave,
  onDone,
}: {
  customer: Customer;
  onSave: (body: {
    first_name: string;
    last_name: string;
    phone: string;
    notes: string;
  }) => Promise<Outcome>;
  onDone: () => void;
}) {
  const [values, setValues] = useState({
    first_name: customer.first_name,
    last_name: customer.last_name,
    phone: formatPhone(customer.phone),
    notes: customer.notes,
  });
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [sending, setSending] = useState(false);
  const errors = (outcome && !outcome.saved && outcome.errors) || {};

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    const result = await onSave(values);
    setSending(false);
    if (result.saved) onDone();
    else setOutcome(result);
  }

  function field(
    name: "first_name" | "last_name" | "phone",
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
    <form onSubmit={submit} autoComplete="off">
      <OutcomeMessage outcome={outcome} />
      {field("first_name", "שם פרטי", { maxLength: 50 })}
      {field("last_name", "שם משפחה", { maxLength: 50 })}
      {field("phone", "טלפון", { type: "tel", dir: "ltr" })}
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
          שמירה
        </button>{" "}
        <button type="button" onClick={onDone} disabled={sending}>
          ביטול
        </button>
      </p>
    </form>
  );
}

function DateOfBirthForm({
  customer,
  onSave,
}: {
  customer: Customer;
  onSave: (dateOfBirth: string) => Promise<Outcome>;
}) {
  const [value, setValue] = useState(customer.date_of_birth);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [sending, setSending] = useState(false);
  const error = outcome && !outcome.saved && outcome.errors?.date_of_birth;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setOutcome(await onSave(value));
    setSending(false);
  }

  return (
    <form onSubmit={submit}>
      <OutcomeMessage outcome={outcome} />
      <p>
        <label htmlFor="date_of_birth">
          תיקון תאריך לידה (קובע את מחיר עד גיל 18)
        </label>{" "}
        <input
          id="date_of_birth"
          type="date"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          required
        />{" "}
        <button
          type="submit"
          disabled={sending || value === customer.date_of_birth}
        >
          שמירה
        </button>{" "}
        {error && <span role="alert">{error}</span>}
      </p>
    </form>
  );
}

function ActiveToggle({
  active,
  onToggle,
}: {
  active: boolean;
  onToggle: () => Promise<Outcome>;
}) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [sending, setSending] = useState(false);

  async function toggle() {
    if (
      active &&
      !window.confirm("להעביר את הלקוח ללא פעיל? הפרטים וההיסטוריה נשמרים.")
    ) {
      return;
    }
    setSending(true);
    setOutcome(await onToggle());
    setSending(false);
  }

  return (
    <>
      <OutcomeMessage outcome={outcome} />
      <p>
        <button type="button" onClick={toggle} disabled={sending}>
          {active ? "העברה ללא פעיל" : "הפעלה מחדש"}
        </button>
      </p>
    </>
  );
}
