"""Request and response shapes of the public API. The public React app's
TypeScript types are generated from these (through the OpenAPI spec)."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from app.core.checkins import Outcome
from app.core.health_form_pdf import SIGNATURE_MAX_BYTES
from app.core.health_forms import FormField, FormState
from app.core.http import Answer, DateOfBirth
from app.core.models import Plan

# Base64 grows bytes by 4/3, plus the "data:image/png;base64," prefix.
SIGNATURE_DATA_URL_MAX_LENGTH = SIGNATURE_MAX_BYTES * 4 // 3 + 100


class Branding(Answer):
    """The gym's name (null before first-run setup) and whether
    ``/branding/logo`` has a logo to show."""

    gym_name: str | None
    has_logo: bool


class Me(Answer):
    """The customer this phone is linked to: only what the page shows."""

    first_name: str
    health_form: "HealthFormStatus"


class NotLinked(Answer):
    """401: this phone has no live link (no cookie, or it was unlinked,
    went unused for a year, or its customer was deactivated). The page
    shows the link form."""

    detail: Literal["not_linked"] = "not_linked"


class LinkRequest(BaseModel):
    # Real values are far shorter; the caps only keep junk out.
    phone: str = Field(max_length=50)
    code: str = Field(max_length=20)


class LinkRefused(Answer):
    """400: the number and code don't link this phone. One answer for
    every reason, so it never says whether a number is a customer's."""

    detail: Literal["link_refused"] = "link_refused"


# ── Signing up (decision 0035) ──────────────────────────────────────────
# The caps on text only keep a huge value out; app.core.customers has the
# real rules and answers a broken field with a code, not a 422.

SignUpField = Literal["first_name", "last_name", "phone", "date_of_birth"]


class SignUpRequest(BaseModel):
    first_name: str = Field(max_length=200)
    last_name: str = Field(max_length=200)
    phone: str = Field(max_length=50)
    date_of_birth: DateOfBirth


class SignUpRefused(Answer):
    """400: every field that breaks its rule, at once. Nothing was
    saved."""

    errors: dict[SignUpField, Literal["invalid"]]


class PhoneTaken(Answer):
    """409: the number is already a customer's (active or not). Nothing
    was saved; the customer links this phone at the desk instead."""

    detail: Literal["phone_taken"] = "phone_taken"


# ── Health form ─────────────────────────────────────────────────────────


class HealthFormStatus(Answer):
    """The customer's health form today. ``valid`` lets them check in;
    ``needs_doctor_note`` (a "yes" answer) and ``missing`` (none, or
    expired) don't. ``valid_until``: the last day of the form that counts,
    or null for ``missing``."""

    state: FormState
    valid_until: date | None


class Question(Answer):
    key: str
    text: str
    # The form has a free-text "details" line after this question.
    has_details: bool


class HealthFormPage(Answer):
    """Everything the phone shows for the current form, in order. The
    customer's details come from their record and can't be changed here.
    ``guardian_consent`` is set when a parent or guardian signs (the
    customer is under 18 today), else null."""

    version: str
    title: str
    customer_name: str
    date_of_birth: date
    phone: str
    wording_note: str
    part_a_title: str
    part_a_notes: list[str]
    questions_intro: str
    questions: list[Question]
    part_b_title: str
    declaration: list[str]
    guardian_title: str
    guardian_consent: str | None
    # What the signed form's "valid until" will say if signed today.
    valid_until_if_signed: date


class HealthFormRequest(BaseModel):
    """A filled-in form. ``signature`` is the signature pad's PNG as a
    data URL (``data:image/png;base64,...``). The caps only keep junk out;
    ``app.core.health_forms`` has the real rules."""

    version: str = Field(max_length=20)
    # Strict: "true" or 1 is not an answer.
    answers: dict[str, StrictBool] = Field(max_length=50)
    details: dict[
        Annotated[str, StringConstraints(max_length=50)],
        Annotated[str, StringConstraints(max_length=1000)],
    ] = Field(default_factory=dict, max_length=10)
    gender: str = Field(max_length=20)
    signer_name: str = Field(max_length=200)
    confirmed: StrictBool
    signature: str = Field(max_length=SIGNATURE_DATA_URL_MAX_LENGTH)


class HealthFormRefused(Answer):
    """400: every field that breaks its rule, at once. Nothing was
    saved."""

    errors: dict[FormField, Literal["invalid"]]


class FormVersionChanged(Answer):
    """409: the form changed while the page was open. Reload the form
    and fill it in again."""

    detail: Literal["form_version_changed"] = "form_version_changed"


# ── Check-in ────────────────────────────────────────────────────────────
# Four digits from 1000 on, then 01-12 (as in the admin API's schemas,
# which this app must not import).
MonthText = Annotated[str, Field(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$")]


class CheckInRequest(BaseModel):
    """``plan``: the option the customer confirmed on the plan page: a plan
    chosen for this month, or ``punch_card`` to buy a card and use its
    first entry. Ignored if a plan or an active card already covers them.
    Leave it out for a plain check-in."""

    plan: Plan | None = None


# The plans a month is chosen for: a punch card never covers a month.
ChosenPlan = Literal["monthly", "tri_monthly", "single_entry"]


class CoveringPlan(Answer):
    """The plan covering this month: one month, or three for tri-monthly
    (``end_month`` is the last)."""

    plan: ChosenPlan
    start_month: MonthText
    end_month: MonthText


class PunchCardBalance(Answer):
    """The punch card that paid for the visit: entries left after it,
    ``expires_on``, the first Israel-local day it no longer counts (the 1st
    of a month), and ``valid_until``, the last day it counts (the day
    before), which is what the phone shows."""

    entries_left: int
    expires_on: date
    valid_until: date


class CheckedIn(Answer):
    """``checked_in``: a visit was recorded. ``already_checked_in``: the
    customer checked in less than 10 minutes ago, and ``checked_in_at`` is
    that visit; nothing new was recorded. Exactly one of ``plan`` and
    ``punch_card`` is set, except for a repeat whose month has since lost
    its plan (both null)."""

    outcome: Outcome
    checked_in_at: datetime
    plan: CoveringPlan | None
    punch_card: PunchCardBalance | None


class HealthFormRequired(Answer):
    """409: no valid health form today; nothing was recorded. Show the
    form (``missing``) or send the customer to the desk
    (``needs_doctor_note``)."""

    detail: Literal["health_form_required"] = "health_form_required"
    health_form: HealthFormStatus


class PlanOffer(Answer):
    """One plan at its price this month.
    ``price_agorot`` null: the price isn't set, so it can't be chosen.
    For the punch card only, ``entries`` is how many it has and
    ``valid_until`` the last day a card bought now counts; both are null
    for the other plans."""

    plan: Plan
    price_agorot: int | None
    entries: int | None
    valid_until: date | None


class PlanRequired(Answer):
    """409: no plan covers ``month``; nothing was recorded. Show the plan
    page and send the tapped plan with the next check-in."""

    detail: Literal["plan_required"] = "plan_required"
    month: MonthText
    options: list[PlanOffer]


class PriceNotSet(Answer):
    """409: the chosen plan's price isn't set (it changed while the page
    was open); nothing was recorded. Check in again for fresh options."""

    detail: Literal["price_not_set"] = "price_not_set"


CheckInRefused = Annotated[
    HealthFormRequired | PlanRequired | PriceNotSet, Field(discriminator="detail")
]
