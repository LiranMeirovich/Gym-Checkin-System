"""Health forms: the official declaration's wording, checking a filled-in
form, how long a form lasts and whether a customer has a valid one (design
doc: "Health form"; decisions 0004, 0031).

The wording lives here, under a version, rather than in React: the server
has to know exactly what was signed to build the PDF snapshot, and old
versions stay here so their forms keep their meaning. A new official form
is a new version; ``CURRENT_VERSION`` is the one customers fill in.

A form with any "yes" answer is saved but doesn't count until staff add a
doctor's note (feature 4), so it blocks check-in like a missing form.
"""

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
from app.core.clock import to_local, utc_now
from app.core.customers import CustomerInactiveError
from app.core.gym_settings import load_gym_settings
from app.core.health_form_pdf import (
    InvalidSignatureError,
    SnapshotDetails,
    check_signature,
    is_printable,
    render_snapshot,
)
from app.core.models import Customer, DoctorNote, HealthForm, StaffUser
from app.core.plans import ADULT_AGE

# How long a form lasts, counted from the day it's signed. Each form keeps
# its own ``expires_on``, so changing this never touches old forms.
VALIDITY_MONTHS = 12

SIGNER_NAME_MAX_LENGTH = 100
DETAILS_MAX_LENGTH = 200


class Gender(StrEnum):
    """The form's gender question. Stored only in the form's answers."""

    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True)
class Question:
    """One yes/no question. ``has_details``: the form has a free-text
    "details" line after it."""

    key: str
    text: str
    has_details: bool = False


@dataclass(frozen=True)
class FormText:
    """Everything a version of the form says, in the order it's shown.
    ``{to_gym}`` in a paragraph becomes "to the gym <name>", the name
    from the gym settings."""

    version: str
    title: str
    # Under the personal details: the masculine wording covers everyone.
    wording_note: str
    part_a_title: str
    part_a_notes: tuple[str, ...]
    questions_intro: str
    questions: tuple[Question, ...]
    part_b_title: str
    declaration: tuple[str, ...]
    # For under-18s, signed by a parent; ``{customer_name}`` is the trainee.
    guardian_title: str
    guardian_consent: str

    def notes(self, gym_name: str | None) -> tuple[str, ...]:
        # As the official form words it: "לחדר כושר <name>". Before
        # first-run setup there's no name yet: "to the gym".
        to_gym = f"לחדר כושר {gym_name}" if gym_name else "לחדר הכושר"
        return tuple(note.format(to_gym=to_gym) for note in self.part_a_notes)

    def consent(self, customer_name: str) -> str:
        return self.guardian_consent.format(customer_name=customer_name)


# The gym's official health declaration (decision 0031), word for word
# except: the gym's name comes from settings, and the form's "valid for
# <year>" lines are replaced by the form's own expiry date where it's shown.
_FORM_2026_11 = FormText(
    version="2026-11",
    title="טופס הצהרת בריאות למתאמן בחדר כושר",
    wording_note="(האמור בשאלון מנוסח בלשון זכר מטעמי נוחות אך מיועד לשני המינים)",
    part_a_title="חלק א': שאלון רפואי",
    part_a_notes=(
        "אם התשובה על אחת מהשאלות, או יותר בחלק זה היא חיובית, אז יש להמציא"
        " {to_gym} גם תעודה רפואית מרופא לפיה הרופא מאשר כי אין סיכון"
        " לבריאותך באימון הכושר. מכון הכושר יקבל מתאמן שהמציא תעודה רפואית"
        " שלא עברו 3 חודשים מיום הנפקתה",
        "אם כל התשובות לשאלות בחלק זה הן שליליות – יש למלא ולחתום על ההצהרה בחלק ב'",
        "בכל מקרה של שינוי במצבך הרפואי, יש להתייעץ עם רופא לגבי המשך הפעילות"
        " בחדר הכושר ולעדכן את המאמנים על כך",
    ),
    questions_intro="האם הנך סובל או סבלת בעבר מ:",
    questions=(
        Question("chronic_illness", "מחלה כרונית"),
        Question("blood_pressure", "לחץ דם גבוה / נמוך"),
        Question("heart_problems", "בעיות לב"),
        Question("stroke", "שבץ"),
        Question("high_cholesterol", "כולסטרול גבוה"),
        Question("diabetes", "סוכרת"),
        Question("surgery_last_year", "ניתוח בשנה האחרונה"),
        Question("knee_ankle_problems", "בעיות ברכיים / קרסול"),
        Question("muscle_joint_pain", "כאבי שרירים / מפרקים"),
        Question("back_neck_problems", "בעיות גב / צוואר"),
        Question("osteoporosis", "אוסטיאופורוזיס"),
        Question("pregnancy", "הריון"),
        Question("difficulty_exercising", "קושי בזמן פעילות גופנית"),
        Question(
            "doctor_advised_no_exercise",
            "עצה מרופא להימנע מפעילות גופנית",
            has_details=True,
        ),
        Question("other", "אחר", has_details=True),
    ),
    part_b_title="חלק ב' - הצהרה",
    declaration=(
        "אני החתום מטה מצהיר כי קראתי והבנתי את כל השאלון שבחלק א' לטופס זה"
        " וכל התשובות שבטופס הן שליליות. אני מצהיר כי אני במצב פיזי טוב וכי"
        " אינני סובל מבעיה רפואית העלולה להתעורר כתוצאה מאימון כושר וכי אני"
        " מסוגל לעסוק באימון אקטיבי או פאסיבי.",
        "השתתפותי בפעילות הכושר הינה באחריותי הבלעדית ואין למאמן בחדר הכושר"
        " ו/או מי מטעמו אחריות לנזק גופני כלשהו העלול להיגרם מכך.",
    ),
    guardian_title="למתאמנים מתחת לגיל 18 נדרשת הסכמת הורים:",
    guardian_consent="אני מסכים כי {customer_name} יתאמן בחדר הכושר בכל סוג אימון.",
)

FORMS: dict[str, FormText] = {_FORM_2026_11.version: _FORM_2026_11}
CURRENT_VERSION = _FORM_2026_11.version


class FormField(StrEnum):
    """The fields a refused form can name."""

    ANSWERS = "answers"
    DETAILS = "details"
    GENDER = "gender"
    SIGNER_NAME = "signer_name"
    CONFIRMED = "confirmed"
    SIGNATURE = "signature"


class InvalidHealthFormError(ValueError):
    """One or more fields break their rule; ``fields`` lists all of them.
    Nothing was saved."""

    def __init__(self, fields: set[FormField]) -> None:
        super().__init__("invalid: " + ", ".join(sorted(fields)))
        self.fields = frozenset(fields)


class FormVersionChangedError(ValueError):
    """The form was filled in on a version that isn't current any more
    (the page was open while the form changed). Reload and fill it in
    again."""


@dataclass(frozen=True)
class CheckedForm:
    """A filled-in form that passed every check, ready to be signed and
    saved. ``details`` holds only the non-empty lines."""

    form: FormText
    answers: dict[str, bool]
    details: dict[str, str]
    gender: Gender
    signer_name: str
    # The clean copy from ``check_signature()``.
    signature_png: bytes

    @property
    def needs_doctor_note(self) -> bool:
        return any(self.answers.values())

    def answers_json_value(self) -> dict[str, object]:
        """What ``health_forms.answers_json`` holds."""
        return {
            "answers": self.answers,
            "details": self.details,
            "gender": self.gender.value,
        }


class FormState(StrEnum):
    VALID = "valid"
    # Signed with a "yes" answer; counts once a doctor's note is added.
    NEEDS_DOCTOR_NOTE = "needs_doctor_note"
    # Never signed, or the newest form has expired.
    MISSING = "missing"


@dataclass(frozen=True)
class HealthFormStatus:
    """What staff and the phone see. ``valid_until`` is the last day of
    the form that counts (also for ``NEEDS_DOCTOR_NOTE``); ``None`` when
    there is none."""

    state: FormState
    valid_until: date | None

    @property
    def allows_check_in(self) -> bool:
        return self.state is FormState.VALID


def expires_on(signed_on: date) -> date:
    """A form's last valid day: the day before its anniversary
    ``VALIDITY_MONTHS`` later. When that date doesn't exist (29 February in
    a common year), the anniversary is the 1st of the next month, so the
    form still lasts the full period and ends on the month's last day."""
    months = signed_on.month - 1 + VALIDITY_MONTHS
    year, month = signed_on.year + months // 12, months % 12 + 1
    if signed_on.day <= calendar.monthrange(year, month)[1]:
        anniversary = date(year, month, signed_on.day)
    else:
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        anniversary = date(next_year, next_month, 1)
    return anniversary - timedelta(days=1)


def signed_by_guardian(customer: Customer, signed_on: date) -> bool:
    """Whether a parent or guardian signs: the customer is under 18 on
    the signing day."""
    born = customer.date_of_birth
    age = signed_on.year - born.year
    if (signed_on.month, signed_on.day) < (born.month, born.day):
        age -= 1
    return age < ADULT_AGE


def check_form(
    *,
    version: str,
    answers: dict[str, bool],
    details: dict[str, str],
    gender: str,
    signer_name: str,
    confirmed: bool,
    signature_png: bytes,
) -> CheckedForm:
    """Check a filled-in form against the current version: every question
    answered, details only where the form has a line for them, a gender, a
    name, the confirmation box ticked and a usable signature image. The
    name and details must be text the PDF can print exactly (Hebrew or
    Latin letters, digits, punctuation), so the signed record never loses
    or garbles them."""
    if version != CURRENT_VERSION:
        raise FormVersionChangedError(version)
    form = FORMS[version]
    keys = {question.key for question in form.questions}
    detail_keys = {q.key for q in form.questions if q.has_details}
    bad: set[FormField] = set()

    if set(answers) != keys or not all(type(v) is bool for v in answers.values()):
        bad.add(FormField.ANSWERS)

    cleaned_details = {key: text.strip() for key, text in details.items()}
    if not set(cleaned_details) <= detail_keys or any(
        len(text) > DETAILS_MAX_LENGTH or not is_printable(text)
        for text in cleaned_details.values()
    ):
        bad.add(FormField.DETAILS)

    if gender not in set(Gender):
        bad.add(FormField.GENDER)

    name = " ".join(signer_name.split())
    if not 1 <= len(name) <= SIGNER_NAME_MAX_LENGTH or not is_printable(name):
        bad.add(FormField.SIGNER_NAME)

    if confirmed is not True:
        bad.add(FormField.CONFIRMED)

    try:
        signature = check_signature(signature_png)
    except InvalidSignatureError:
        bad.add(FormField.SIGNATURE)

    if bad:
        raise InvalidHealthFormError(bad)
    return CheckedForm(
        form=form,
        # In the form's order, so the stored JSON reads like the form.
        answers={q.key: answers[q.key] for q in form.questions},
        details={key: text for key, text in cleaned_details.items() if text},
        gender=Gender(gender),
        signer_name=name,
        signature_png=signature,
    )


def local_today() -> date:
    """Today in Israel time: the day a form is signed or checked on."""
    return to_local(utc_now()).date()


def save_form(
    db: Session, customer: Customer, checked: CheckedForm, *, today: date
) -> HealthForm:
    """Sign and store a checked form for ``customer`` on ``today``, with
    its PDF snapshot. Works in the caller's transaction and never commits.

    Not logged: the customer fills it in themselves, on their phone or on
    a gym device (decision 0031). The PDF is built inside the transaction
    (decision 0031: moved out only if it proves slow).
    """
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    guardian = signed_by_guardian(customer, today)
    last_day = expires_on(today)
    document = render_snapshot(
        checked,
        SnapshotDetails(
            gym_name=load_gym_settings(db).gym_name,
            customer_name=f"{customer.first_name} {customer.last_name}",
            date_of_birth=customer.date_of_birth,
            phone=customer.phone,
            signed_on=today,
            expires_on=last_day,
            signed_by_guardian=guardian,
        ),
        checked.signature_png,
    )
    form = HealthForm(
        customer_id=customer.id,
        form_version=checked.form.version,
        answers_json=json.dumps(checked.answers_json_value(), ensure_ascii=False),
        needs_doctor_note=checked.needs_doctor_note,
        signer_name=checked.signer_name,
        signed_by_guardian=guardian,
        signed_on=today,
        expires_on=last_day,
        document=document,
    )
    db.add(form)
    db.flush()
    return form


def list_forms(db: Session, customer: Customer) -> list[HealthForm]:
    """Every form the customer has signed, newest first. The PDFs stay
    unloaded."""
    return list(
        db.scalars(
            select(HealthForm)
            .where(HealthForm.customer_id == customer.id)
            .order_by(HealthForm.signed_on.desc(), HealthForm.id.desc())
        )
    )


def form_of(db: Session, customer: Customer, form_id: int) -> HealthForm | None:
    """One of the customer's forms, or None if ``form_id`` isn't theirs."""
    form = db.get(HealthForm, form_id)
    return form if form is not None and form.customer_id == customer.id else None


def open_form_document(db: Session, form: HealthForm, *, by: StaffUser) -> bytes:
    """A form's PDF, for the manager. Every opening is written to the
    activity log (design doc: "Validity and access"); the caller checks
    ``health_forms.view_contents``."""
    record(db, by, Action.HEALTH_FORM_OPEN, Target.HEALTH_FORM, form.id)
    return form.document


def health_form_status(
    db: Session, customer: Customer, today: date
) -> HealthFormStatus:
    """The customer's health form on ``today`` (an Israel-local date): the
    status of ``counting_form()``."""
    return status_of(db, counting_form(db, customer, today))


def counting_form(db: Session, customer: Customer, today: date) -> HealthForm | None:
    """The form that counts for ``customer`` on ``today``: the newest one
    that hasn't expired, even if an older one has no "yes" (a newer "yes"
    means their health changed). ``None`` when there is none."""
    return db.scalars(
        select(HealthForm)
        .where(HealthForm.customer_id == customer.id, HealthForm.expires_on >= today)
        .order_by(HealthForm.signed_on.desc(), HealthForm.id.desc())
        .limit(1)
    ).first()


def status_of(db: Session, form: HealthForm | None) -> HealthFormStatus:
    """The status of the form that counts (``None``: missing). A form with
    a "yes" is valid once a doctor's note has been added for it."""
    if form is None:
        return HealthFormStatus(FormState.MISSING, None)
    if form.needs_doctor_note and not has_doctor_note(db, form):
        return HealthFormStatus(FormState.NEEDS_DOCTOR_NOTE, form.expires_on)
    return HealthFormStatus(FormState.VALID, form.expires_on)


def has_doctor_note(db: Session, form: HealthForm) -> bool:
    """Whether staff have added a doctor's note for ``form``."""
    return bool(db.scalar(select(exists().where(DoctorNote.health_form_id == form.id))))
