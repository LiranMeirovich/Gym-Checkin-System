// The health form on the admin PC (decision 0031): for a customer without a
// smartphone, who fills it in and signs it here at the desk. The shared
// form (src/shared/HealthForm.tsx) wired to the admin API, on a screen with
// no staff header. The server logs which staff member opened it. Once
// signed, or on Cancel, it goes back to the customer's page.
//
// The PC never becomes the customer's device: no gym_device cookie here.
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
import {
  HealthForm,
  type FilledInForm,
  type HealthFormField,
  type HealthFormPage,
  type SubmitOutcome,
} from "../../shared/HealthForm";
import { api, type Schemas } from "../backend/client";
import { healthFormKey, healthFormsKey } from "../customers";
import ui from "../layout/ui.module.css";

type Status = Schemas["HealthFormStatus"];

async function load(id: number): Promise<HealthFormPage> {
  const { data, response } = await api.GET(
    "/api/customers/{customer_id}/health-form/fill-in",
    { params: { path: { customer_id: id } } },
  );
  if (data) return data;
  throw new Error(`GET health-form/fill-in failed: ${response.status}`);
}

async function submit(
  id: number,
  form: FilledInForm,
): Promise<SubmitOutcome<Status>> {
  const { data, error, response } = await api.POST(
    "/api/customers/{customer_id}/health-form/fill-in",
    { params: { path: { customer_id: id } }, body: form },
  );
  if (data) return { outcome: "signed", status: data };
  if (response.status === 400 && error && "errors" in error) {
    return {
      outcome: "invalid",
      fields: Object.keys(error.errors) as HealthFormField[],
    };
  }
  if (response.status === 409 && error && "error" in error) {
    if (error.error === "form_version_changed") {
      return { outcome: "version_changed" };
    }
    return {
      outcome: "refused",
      message: "הלקוח לא פעיל. יש להפעיל אותו מחדש קודם.",
    };
  }
  return { outcome: "refused", message: "משהו השתבש. נסו שוב בעוד רגע." };
}

export function FillInHealthForm() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const back = `/customers/${id}`;

  return (
    <>
      <p>
        <Link className={ui.back} to={back}>
          ביטול וחזרה לכרטיס הלקוח
        </Link>
      </p>
      <HealthForm
        queryKey={["customers", id, "health-form-to-fill-in"]}
        load={() => load(id)}
        submit={(form) => submit(id, form)}
        onSigned={(status) => {
          queryClient.setQueryData(healthFormKey(id), status);
          // The manager's list of signed forms has a new row.
          void queryClient.invalidateQueries({
            queryKey: healthFormsKey(id),
          });
          navigate(back, { replace: true });
        }}
      />
    </>
  );
}
