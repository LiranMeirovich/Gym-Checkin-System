// The health form on the customer's phone: the shared form
// (src/shared/HealthForm.tsx) wired to the public API.
import {
  HealthForm as SharedHealthForm,
  type FilledInForm,
  type HealthFormField,
  type HealthFormPage,
  type SubmitOutcome,
} from "../../shared/HealthForm";
import { api, type Schemas } from "../backend/client";

type Status = Schemas["HealthFormStatus"];

const QUERY_KEY = ["health-form"] as const;

async function load(): Promise<HealthFormPage> {
  const { data, response } = await api.GET("/api/health-form");
  if (data) return data;
  throw new Error(`GET /api/health-form failed: ${response.status}`);
}

async function submit(form: FilledInForm): Promise<SubmitOutcome<Status>> {
  const { data, error, response } = await api.POST("/api/health-form", {
    body: form,
  });
  if (data) return { outcome: "signed", status: data };
  if (response.status === 409) return { outcome: "version_changed" };
  if (response.status === 400 && error && "errors" in error) {
    return {
      outcome: "invalid",
      fields: Object.keys(error.errors) as HealthFormField[],
    };
  }
  return { outcome: "refused", message: "משהו השתבש. נסו שוב בעוד רגע." };
}

type Props = {
  /** Called with the new status once the form is saved. */
  onSigned: (status: Status) => void;
};

export function HealthForm({ onSigned }: Props) {
  return (
    <SharedHealthForm
      queryKey={QUERY_KEY}
      load={load}
      submit={submit}
      onSigned={onSigned}
    />
  );
}
