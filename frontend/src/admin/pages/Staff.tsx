// The staff accounts, for the owner and managers (staff.manage; decisions
// 0018, 0037, 0039): who can log in, who is locked out, and the changes:
// add, reset a PIN, change a role, deactivate and reactivate. Which
// changes each account allows is the server's rule (app/core/staff.py):
// every listed member comes with can_reset_pin, can_change_role and
// can_toggle_active, and this screen offers only those.

import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "../backend/client";
import { formatDate, formatTime } from "../customers";
import { Field, PageHead } from "../layout/ui";
import ui from "../layout/ui.module.css";
import { can } from "../roles";
import { ROLE_NAMES, useSession } from "../session";
import { Forbidden, STAFF_KEY, fetchStaff } from "../staff";
import {
  NoConnection,
  NO_CONNECTION_TRY_AGAIN,
} from "../../shared/NoConnection";
import { StatusBadge } from "../../shared/Status";
import styles from "./Staff.module.css";

type Member = Schemas["StaffMember"];
// The roles an account can be given; the owner is made only at setup.
type Role = Schemas["RoleChange"]["role"];
// The fields a 400 can name (the API types its errors as a plain map).
type StaffField = "display_name" | "pin";
type Conflict = Schemas["StaffConflict"]["error"];

const FIELD_ERRORS: Record<StaffField, string> = {
  display_name: "שם: 1 עד 50 תווים, בלי תווים נסתרים",
  pin: "קוד: 6 עד 12 ספרות, לא ספרה אחת חוזרת ולא רצף (כמו 123456)",
};

const CONFLICTS: Record<Conflict, string> = {
  name_taken: "לאיש צוות פעיל אחר כבר יש את השם הזה.",
  owner:
    "את חשבון הבעלים אי אפשר להוריד בתפקיד או להשבית, ורק הבעלים מאפסים את הקוד שלהם.",
};

/** What a change came back with, for the message above the table. */
type Outcome = { ok: boolean; text: string };

/** A change's answer: the changed member, or a refusal to show. */
type Answer = {
  data?: Member;
  error?: unknown;
  response: Response;
};

function outcomeOf(answer: Answer, done: string): Outcome {
  if (answer.data) return { ok: true, text: done };
  const error = answer.error as { error?: Conflict } | undefined;
  if (answer.response.status === 409 && error?.error) {
    return { ok: false, text: CONFLICTS[error.error] };
  }
  if (answer.response.status === 403) {
    return { ok: false, text: "רק הבעלים יכולים לשנות חשבונות של מנהלים." };
  }
  if (answer.response.status === 404) {
    return { ok: false, text: "איש הצוות לא נמצא. רעננו את הדף." };
  }
  return { ok: false, text: "השמירה נכשלה. נסו שוב." };
}

export function Staff() {
  const queryClient = useQueryClient();
  // No retries: a refusal won't change, and each request counts as
  // activity for the auto-lock.
  const staff = useQuery({
    queryKey: STAFF_KEY,
    queryFn: fetchStaff,
    retry: false,
  });
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [resetting, setResetting] = useState<Member | null>(null);

  async function change(send: () => Promise<Answer>, done: string) {
    setOutcome(null);
    try {
      setOutcome(outcomeOf(await send(), done));
    } catch {
      setOutcome({ ok: false, text: NO_CONNECTION_TRY_AGAIN });
    }
    // Refetched either way: the list is sorted by the server (active
    // first), and a refusal may mean someone else changed it meanwhile.
    await queryClient.invalidateQueries({ queryKey: STAFF_KEY });
  }

  if (staff.error instanceof Forbidden) {
    return (
      <>
        <PageHead title="צוות" />
        <p role="alert">ניהול הצוות פתוח למנהלים בלבד.</p>
      </>
    );
  }

  return (
    <>
      <PageHead title="צוות" />
      {outcome && (
        <p role={outcome.ok ? "status" : "alert"} className={styles.outcome}>
          {outcome.text}
        </p>
      )}
      {staff.isPending ? null : staff.isError ? (
        <NoConnection />
      ) : (
        <StaffTable
          staff={staff.data}
          onReset={(member) => {
            setOutcome(null);
            setResetting(member);
          }}
          onChange={change}
        />
      )}
      {resetting && (
        <ResetPinForm
          // A new member starts an empty form.
          key={resetting.id}
          member={resetting}
          onDone={(text) => {
            setResetting(null);
            setOutcome({ ok: true, text });
            void queryClient.invalidateQueries({ queryKey: STAFF_KEY });
          }}
          onCancel={() => setResetting(null)}
        />
      )}
      <AddForm
        onAdded={(member) => {
          setOutcome({
            ok: true,
            text: `${member.display_name} נוסף/ה. השם מופיע עכשיו במסך הנעילה.`,
          });
          void queryClient.invalidateQueries({ queryKey: STAFF_KEY });
        }}
      />
    </>
  );
}

function StaffTable({
  staff,
  onReset,
  onChange,
}: {
  staff: Member[];
  onReset: (member: Member) => void;
  onChange: (send: () => Promise<Answer>, done: string) => Promise<void>;
}) {
  const session = useSession();
  const [busy, setBusy] = useState<number | null>(null);

  async function run(
    member: Member,
    send: () => Promise<Answer>,
    done: string,
  ) {
    setBusy(member.id);
    await onChange(send, done);
    setBusy(null);
  }

  function changeRole(member: Member) {
    const role: Role = member.role === "manager" ? "instructor" : "manager";
    const question =
      role === "manager"
        ? `לתת ל${member.display_name} הרשאות מנהל/ת? מנהלים יכולים לשנות מחירים, הגדרות וצוות.`
        : `להעביר את ${member.display_name} לתפקיד מדריך/ה?`;
    if (!window.confirm(question)) return;
    void run(
      member,
      () =>
        api.PUT("/api/staff/{staff_id}/role", {
          params: { path: { staff_id: member.id } },
          body: { role },
        }),
      `${member.display_name}: התפקיד שונה ל${ROLE_NAMES[role]}.`,
    );
  }

  function toggleActive(member: Member) {
    if (member.active) {
      if (
        !window.confirm(
          `להשבית את ${member.display_name}? לא יוכל/תוכל להתחבר, והפעולות שלו/ה נשארות ביומן.`,
        )
      ) {
        return;
      }
    }
    const path = member.active
      ? "/api/staff/{staff_id}/deactivate"
      : "/api/staff/{staff_id}/reactivate";
    void run(
      member,
      () => api.POST(path, { params: { path: { staff_id: member.id } } }),
      member.active
        ? `${member.display_name} הושבת/ה.`
        : `${member.display_name} הופעל/ה מחדש.`,
    );
  }

  return (
    <div className={ui.tablePanel}>
      <table>
        <thead>
          <tr>
            <th>שם</th>
            <th>תפקיד</th>
            <th>מצב</th>
            <th>
              <span className={styles.hidden}>פעולות</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {staff.map((member) => {
            const self = member.id === session.staff.id;
            return (
              <tr
                key={member.id}
                className={member.active ? undefined : styles.inactive}
              >
                <td>
                  {member.display_name}
                  {self && <span className={styles.self}> (את/ה)</span>}
                </td>
                <td>{ROLE_NAMES[member.role]}</td>
                <td>
                  <MemberStatus member={member} />
                </td>
                <td className={ui.rowAction}>
                  <div className={styles.rowButtons}>
                    {member.can_reset_pin && (
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => onReset(member)}
                      >
                        איפוס קוד
                      </button>
                    )}
                    {member.can_change_role && (
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => changeRole(member)}
                      >
                        {member.role === "manager"
                          ? "העברה למדריך/ה"
                          : "הפיכה למנהל/ת"}
                      </button>
                    )}
                    {member.can_toggle_active && (
                      <button
                        type="button"
                        className={member.active ? ui.quiet : undefined}
                        disabled={busy !== null}
                        onClick={() => toggleActive(member)}
                      >
                        {member.active ? "השבתה" : "הפעלה מחדש"}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MemberStatus({ member }: { member: Member }) {
  if (!member.active) return <StatusBadge tone="stop">לא פעיל/ה</StatusBadge>;
  if (member.locked_until) {
    return (
      <StatusBadge tone="warn">
        נעול/ה עד{" "}
        <span dir="ltr">
          {formatTime(member.locked_until)}, {formatDate(member.locked_until)}
        </span>
      </StatusBadge>
    );
  }
  return <StatusBadge tone="ok">פעיל/ה</StatusBadge>;
}

function PinInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <input
      id={id}
      className={styles.pin}
      type="password"
      inputMode="numeric"
      pattern="[0-9]{6,12}"
      dir="ltr"
      autoComplete="new-password"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      required
    />
  );
}

function ResetPinForm({
  member,
  onDone,
  onCancel,
}: {
  member: Member;
  onDone: (text: string) => void;
  onCancel: () => void;
}) {
  const session = useSession();
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const self = member.id === session.staff.id;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSending(true);
    try {
      const answer = await api.PUT("/api/staff/{staff_id}/pin", {
        params: { path: { staff_id: member.id } },
        body: { pin },
      });
      if (answer.data) {
        onDone(
          self
            ? "הקוד שלך הוחלף."
            : `הקוד של ${member.display_name} הוחלף, וכל ההתחברויות הפתוחות שלו/ה נסגרו.`,
        );
        return;
      }
      setPin("");
      setError(
        answer.response.status === 400
          ? FIELD_ERRORS.pin
          : outcomeOf(answer, "").text,
      );
    } catch {
      setError(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <h2 className={ui.sectionTitle}>קוד חדש ל{member.display_name}</h2>
      <form className={ui.panel} onSubmit={submit} autoComplete="off">
        <p className={ui.muted}>
          {self
            ? "הקוד החדש יחליף את הקוד הנוכחי שלך. ההתחברות כאן נשארת פתוחה."
            : "הקוד החדש מבטל נעילה, ומי שמחובר/ת כרגע בשם הזה ינותק/תנותק. מסרו את הקוד ל" +
              member.display_name +
              " באופן אישי."}
        </p>
        <Field id="reset_pin" label="קוד חדש (6 עד 12 ספרות)" error={error}>
          <PinInput id="reset_pin" value={pin} onChange={setPin} />
        </Field>
        <div className={ui.buttons}>
          <button type="submit" className={ui.primary} disabled={sending}>
            שמירת הקוד
          </button>
          <button type="button" onClick={onCancel} disabled={sending}>
            ביטול
          </button>
        </div>
      </form>
    </>
  );
}

function AddForm({ onAdded }: { onAdded: (member: Member) => void }) {
  const session = useSession();
  const managesManagers = can(session, "staff.manage_managers");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("instructor");
  const [pin, setPin] = useState("");
  const [errors, setErrors] = useState<Partial<Record<StaffField, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setErrors({});
    setFormError(null);
    setSending(true);
    try {
      const answer = await api.POST("/api/staff", {
        body: { display_name: name, role, pin },
      });
      if (answer.data) {
        setName("");
        setRole("instructor");
        setPin("");
        onAdded(answer.data);
        return;
      }
      // The PIN is typed again after any refusal; the name stays.
      setPin("");
      if (answer.response.status === 400 && answer.error) {
        const refused = answer.error as Schemas["StaffRefused"];
        setErrors(
          Object.fromEntries(
            Object.keys(refused.errors).map((field) => [
              field,
              FIELD_ERRORS[field as StaffField],
            ]),
          ),
        );
      } else {
        setFormError(outcomeOf(answer, "").text);
      }
    } catch {
      setFormError(NO_CONNECTION_TRY_AGAIN);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <h2 className={ui.sectionTitle}>איש צוות חדש</h2>
      <form className={ui.panel} onSubmit={submit} autoComplete="off">
        <p className={ui.muted}>
          השם מופיע במסך הנעילה. מסרו את הקוד לאיש הצוות באופן אישי.
        </p>
        {formError && <p role="alert">{formError}</p>}
        <div className={ui.pair}>
          <Field id="new_name" label="שם" error={errors.display_name}>
            <input
              id="new_name"
              value={name}
              maxLength={50}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </Field>
          {/* Only the owner adds managers; a manager adds instructors. */}
          {managesManagers && (
            <Field id="new_role" label="תפקיד">
              <select
                id="new_role"
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
              >
                <option value="instructor">{ROLE_NAMES.instructor}</option>
                <option value="manager">{ROLE_NAMES.manager}</option>
              </select>
            </Field>
          )}
          <Field id="new_pin" label="קוד (6 עד 12 ספרות)" error={errors.pin}>
            <PinInput id="new_pin" value={pin} onChange={setPin} />
          </Field>
        </div>
        <div className={ui.buttons}>
          <button type="submit" className={ui.primary} disabled={sending}>
            הוספה
          </button>
        </div>
      </form>
    </>
  );
}
