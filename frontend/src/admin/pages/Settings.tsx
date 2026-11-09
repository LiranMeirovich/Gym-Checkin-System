// The gym settings, for the owner and managers (settings.edit; decisions
// 0016, 0037): the gym's name, the manager's email, the report's
// recipients and the two lock times. The rules are the server's
// (app/core/gym_settings.py): the whole form is saved at once, and a
// refusal names the broken fields, which this screen explains in Hebrew.
// A stored value the server can't read shows its default, with a note, so
// saving the form repairs it.

import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { BRANDING_KEY } from "../branding";
import { Field, PageHead, Panel } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { SESSION_KEY } from "../session";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
} from "../../shared/NoConnection";
import styles from "./Settings.module.css";

type Settings = Schemas["GymSettingsAnswer"];
type SettingsField = Settings["problems"][number];
type Refused = Schemas["SettingsRefused"];

const SETTINGS_KEY = ["settings"] as const;

/** The server refused the settings: this role can't edit them. */
class Forbidden extends Error {}

async function fetchSettings(): Promise<Settings> {
  const { data, response } = await api.GET("/api/settings");
  if (data) return data;
  if (response.status === 403) throw new Forbidden();
  throw new Error(`GET /api/settings failed: ${response.status}`);
}

const MANAGER_MAX = 60;
const INSTRUCTOR_MAX = 720;

const FIELD_ERRORS: Record<SettingsField, string> = {
  gym_name: "שם המכון: 1 עד 100 תווים.",
  manager_email:
    "כתובת אימייל לא תקינה. אותיות באנגלית, ספרות וסימנים, בלי רווחים.",
  report_recipients: "יש ברשימה כתובת לא תקינה.",
  lock_screen_minutes: `מספר שלם בין 1 ל־${MANAGER_MAX}.`,
  instructor_lock_screen_minutes: `מספר שלם בין 1 ל־${INSTRUCTOR_MAX}.`,
};
const DUPLICATE_RECIPIENT = "אותה כתובת מופיעה ברשימה פעמיים.";
const BAD_RECIPIENT = "כתובת לא תקינה.";
const BROKEN_STORED_VALUE =
  "הערך השמור לא היה תקין, ולכן מוצג ערך ברירת המחדל. שמירה תתקן אותו.";

export function Settings() {
  const settings = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: fetchSettings,
    // No retries: a refusal won't change, and each request counts as
    // activity for the auto-lock.
    retry: false,
  });

  if (settings.error instanceof Forbidden) {
    return (
      <>
        <PageHead title="הגדרות" />
        <p role="alert">ההגדרות פתוחות למנהלים בלבד.</p>
      </>
    );
  }
  return (
    <>
      <PageHead title="הגדרות" />
      {settings.isPending ? null : settings.isError ? (
        <NoConnection />
      ) : (
        <SettingsForm settings={settings.data} />
      )}
    </>
  );
}

/** The form's own text, before it becomes the request. */
type Draft = {
  gymName: string;
  managerEmail: string;
  recipients: string[];
  managerMinutes: string;
  instructorMinutes: string;
};

function draftOf(settings: Settings): Draft {
  return {
    gymName: settings.gym_name ?? "",
    managerEmail: settings.manager_email ?? "",
    recipients: [...settings.report_recipients],
    managerMinutes: String(settings.lock_screen_minutes),
    instructorMinutes: String(settings.instructor_lock_screen_minutes),
  };
}

/** Whole minutes, or null if the text isn't a whole number. */
function minutesOf(text: string): number | null {
  const trimmed = text.trim();
  return /^\d{1,6}$/.test(trimmed) ? Number(trimmed) : null;
}

/** What a field shows under it after a save: its error, if any. */
type Errors = Partial<Record<SettingsField, string>>;

function SettingsForm({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => draftOf(settings));
  const [problems, setProblems] = useState(settings.problems);
  const [errors, setErrors] = useState<Errors>({});
  // Positions in draft.recipients of the addresses the server refused.
  const [badRecipients, setBadRecipients] = useState<number[]>([]);
  const [sending, setSending] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  function update(change: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...change }));
  }

  function setRecipient(position: number, value: string) {
    update({
      recipients: draft.recipients.map((r, i) => (i === position ? value : r)),
    });
  }

  function removeRecipient(position: number) {
    update({ recipients: draft.recipients.filter((_, i) => i !== position) });
    // The rows after it move up; their marks would point at the wrong row.
    setBadRecipients([]);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setOutcome(null);

    // Whole numbers are checked here: the server takes only numbers, so
    // text it can't read would be a malformed request, not a field error.
    const managerMinutes = minutesOf(draft.managerMinutes);
    const instructorMinutes = minutesOf(draft.instructorMinutes);
    const local: Errors = {};
    if (managerMinutes === null) {
      local.lock_screen_minutes = FIELD_ERRORS.lock_screen_minutes;
    }
    if (instructorMinutes === null) {
      local.instructor_lock_screen_minutes =
        FIELD_ERRORS.instructor_lock_screen_minutes;
    }
    if (managerMinutes === null || instructorMinutes === null) {
      setErrors(local);
      setBadRecipients([]);
      return;
    }

    // Empty rows are dropped; `sent` maps each sent address back to its
    // row, so a refused address is marked on the right one.
    const sent = draft.recipients
      .map((address, row) => ({ address: address.trim(), row }))
      .filter(({ address }) => address !== "");
    const email = draft.managerEmail.trim();

    setSending(true);
    try {
      const { data, error, response } = await api.PUT("/api/settings", {
        body: {
          gym_name: draft.gymName,
          manager_email: email === "" ? null : email,
          report_recipients: sent.map(({ address }) => address),
          lock_screen_minutes: managerMinutes,
          instructor_lock_screen_minutes: instructorMinutes,
        },
      });
      if (data) {
        queryClient.setQueryData(SETTINGS_KEY, data);
        setDraft(draftOf(data));
        setProblems(data.problems);
        setErrors({});
        setBadRecipients([]);
        setOutcome({ ok: true, text: "ההגדרות נשמרו." });
        // The lock times reach the auto-lock timer through the session
        // answer, and the gym's name reaches the header through branding.
        void queryClient.invalidateQueries({ queryKey: SESSION_KEY });
        void queryClient.invalidateQueries({ queryKey: BRANDING_KEY });
      } else if (response.status === 400 && error) {
        const refused = error as Refused;
        const shown: Errors = {};
        for (const [field, code] of Object.entries(refused.errors)) {
          const name = field as SettingsField;
          // A bad address is marked on its own row instead (below).
          if (name === "report_recipients" && code === "invalid") continue;
          shown[name] =
            code === "duplicate" ? DUPLICATE_RECIPIENT : FIELD_ERRORS[name];
        }
        setErrors(shown);
        setBadRecipients(
          refused.bad_recipients
            .map((position) => sent[position]?.row)
            .filter((row) => row !== undefined),
        );
        setOutcome({ ok: false, text: "לא נשמר דבר. תקנו את השדות המסומנים." });
      } else if (response.status === 403) {
        setOutcome({ ok: false, text: "ההגדרות פתוחות למנהלים בלבד." });
      } else {
        setOutcome({ ok: false, text: "השמירה נכשלה. נסו שוב." });
      }
    } catch {
      setOutcome({ ok: false, text: NO_CONNECTION_TRY_AGAIN });
    } finally {
      setSending(false);
    }
  }

  const note = (field: SettingsField) =>
    problems.includes(field) ? (
      <p className={ui.note}>{BROKEN_STORED_VALUE}</p>
    ) : null;

  return (
    <form className={ui.form} onSubmit={submit} noValidate>
      <Panel title="המכון">
        <Field id="gym-name" label="שם המכון" error={errors.gym_name}>
          <input
            id="gym-name"
            value={draft.gymName}
            maxLength={100}
            onChange={(e) => update({ gymName: e.target.value })}
          />
        </Field>
        {note("gym_name")}
        <p className={ui.note}>מופיע בכותרת, במסך הנעילה ובהצהרת הבריאות.</p>
      </Panel>

      <Panel title="הדוח החודשי">
        <Field
          id="manager-email"
          label="אימייל המנהל"
          error={errors.manager_email}
        >
          <input
            id="manager-email"
            type="email"
            dir="ltr"
            autoComplete="off"
            value={draft.managerEmail}
            onChange={(e) => update({ managerEmail: e.target.value })}
          />
        </Field>
        {note("manager_email")}
        <p className={ui.note}>
          מקבל את הדוח ראשון, לבדיקה ולאישור. אפשר להשאיר ריק.
        </p>

        <fieldset className={styles.recipients}>
          <legend>מקבלי הדוח אחרי האישור</legend>
          {draft.recipients.length === 0 && (
            <p className={ui.muted}>אין מקבלים. הדוח יישלח רק למנהל.</p>
          )}
          {draft.recipients.map((address, position) => {
            const id = `recipient-${position}`;
            const bad = badRecipients.includes(position);
            return (
              <div key={position} className={styles.recipient}>
                <label htmlFor={id} className={styles.hidden}>
                  {`נמען ${position + 1}`}
                </label>
                <input
                  id={id}
                  type="email"
                  dir="ltr"
                  autoComplete="off"
                  value={address}
                  aria-invalid={bad || undefined}
                  onChange={(e) => setRecipient(position, e.target.value)}
                />
                <button
                  type="button"
                  className={ui.quiet}
                  onClick={() => removeRecipient(position)}
                >
                  הסרה
                </button>
                {bad && (
                  <span role="alert" className={styles.rowError}>
                    {BAD_RECIPIENT}
                  </span>
                )}
              </div>
            );
          })}
          {errors.report_recipients && (
            <p role="alert" className={styles.listError}>
              {errors.report_recipients}
            </p>
          )}
          {note("report_recipients")}
          <button
            type="button"
            onClick={() => update({ recipients: [...draft.recipients, ""] })}
          >
            הוספת נמען
          </button>
        </fieldset>
      </Panel>

      <Panel title="נעילת המסך">
        <div className={ui.pair}>
          <Field
            id="manager-minutes"
            label="מנהלים: נעילה אחרי (דקות)"
            error={errors.lock_screen_minutes}
          >
            <input
              id="manager-minutes"
              inputMode="numeric"
              className={styles.minutes}
              value={draft.managerMinutes}
              onChange={(e) => update({ managerMinutes: e.target.value })}
            />
          </Field>
          <Field
            id="instructor-minutes"
            label="מדריכים: נעילה אחרי (דקות)"
            error={errors.instructor_lock_screen_minutes}
          >
            <input
              id="instructor-minutes"
              inputMode="numeric"
              className={styles.minutes}
              value={draft.instructorMinutes}
              onChange={(e) => update({ instructorMinutes: e.target.value })}
            />
          </Field>
        </div>
        {note("lock_screen_minutes")}
        {note("instructor_lock_screen_minutes")}
        <p className={ui.note}>
          {`כמה דקות בלי פעולה עד שהמסך ננעל. מנהלים: 1 עד ${MANAGER_MAX}, מדריכים: 1 עד ${INSTRUCTOR_MAX}. השינוי חל מיד על כל מי שמחובר.`}
        </p>
      </Panel>

      <div className={ui.buttons}>
        <button type="submit" disabled={sending}>
          שמירה
        </button>
        {/* Next to the button, where the manager is looking after a save. */}
        {outcome && (
          <p role={outcome.ok ? "status" : "alert"} className={styles.outcome}>
            {outcome.text}
          </p>
        )}
      </div>
    </form>
  );
}
