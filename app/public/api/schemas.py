"""Request and response shapes of the public API. The public React app's
TypeScript types are generated from these (through the OpenAPI spec)."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from app.core.health_form_pdf import SIGNATURE_MAX_BYTES
from app.core.health_forms import FormField, FormState
from app.core.http import Answer

# Base64 grows bytes by 4/3, plus the "data:image/png;base64," prefix.
SIGNATURE_DATA_URL_MAX_LENGTH = SIGNATURE_MAX_BYTES * 4 // 3 + 100


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
