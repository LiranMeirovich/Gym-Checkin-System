"""The health form on the customer's phone (design doc: "Health form";
decisions 0004, 0031). Only a linked phone gets it; anything else is 401
``not_linked``, and the page shows the link form.

- ``GET /api/health-form``: the current form's wording and the customer's
  details, for the phone to show.
- ``POST /api/health-form``: the filled-in form with its signature. The
  answer is the customer's health form status afterwards: ``valid``, or
  ``needs_doctor_note`` when an answer was "yes". 400 lists every bad
  field; 409 means the form changed while the page was open.

Filling in a form doesn't count as using the phone (``last_seen_at``); a
check-in does (``POST /api/check-in``).
"""

import base64
import binascii

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.customers import display_phone
from app.core.db import DbSession
from app.core.gym_settings import load_gym_settings
from app.core.health_forms import (
    CURRENT_VERSION,
    FORMS,
    FormVersionChangedError,
    InvalidHealthFormError,
    check_form,
    expires_on,
    health_form_status,
    local_today,
    save_form,
    signed_by_guardian,
)
from app.core.health_forms import HealthFormStatus as CoreStatus
from app.public.api.schemas import (
    FormVersionChanged,
    HealthFormPage,
    HealthFormRefused,
    HealthFormRequest,
    HealthFormStatus,
    NotLinked,
    Question,
)
from app.public.device import refuse_not_linked, this_device

router = APIRouter()

_PNG_DATA_URL = "data:image/png;base64,"

NOT_LINKED = {status.HTTP_401_UNAUTHORIZED: {"model": NotLinked}}


def status_answer(found: CoreStatus) -> HealthFormStatus:
    return HealthFormStatus(state=found.state, valid_until=found.valid_until)


@router.get("/health-form", response_model=HealthFormPage, responses=NOT_LINKED)
def health_form_page(request: Request, db: DbSession) -> HealthFormPage | JSONResponse:
    device = this_device(request, db)
    if device is None:
        return refuse_not_linked(request)
    customer = device.customer
    today = local_today()
    form = FORMS[CURRENT_VERSION]
    name = f"{customer.first_name} {customer.last_name}"
    return HealthFormPage(
        version=form.version,
        title=form.title,
        customer_name=name,
        date_of_birth=customer.date_of_birth,
        phone=display_phone(customer.phone),
        wording_note=form.wording_note,
        part_a_title=form.part_a_title,
        part_a_notes=list(form.notes(load_gym_settings(db).gym_name)),
        questions_intro=form.questions_intro,
        questions=[
            Question(key=q.key, text=q.text, has_details=q.has_details)
            for q in form.questions
        ],
        part_b_title=form.part_b_title,
        declaration=list(form.declaration),
        guardian_title=form.guardian_title,
        guardian_consent=(
            form.consent(name) if signed_by_guardian(customer, today) else None
        ),
        valid_until_if_signed=expires_on(today),
    )


@router.post(
    "/health-form",
    response_model=HealthFormStatus,
    responses={
        **NOT_LINKED,
        status.HTTP_400_BAD_REQUEST: {"model": HealthFormRefused},
        status.HTTP_409_CONFLICT: {"model": FormVersionChanged},
    },
)
def sign_health_form(
    body: HealthFormRequest, request: Request, db: DbSession
) -> HealthFormStatus | JSONResponse:
    device = this_device(request, db)
    if device is None:
        return refuse_not_linked(request)
    try:
        checked = check_form(
            version=body.version,
            answers=body.answers,
            details=body.details,
            gender=body.gender,
            signer_name=body.signer_name,
            confirmed=body.confirmed,
            signature_png=_png_bytes(body.signature),
        )
    except FormVersionChangedError:
        return JSONResponse(
            FormVersionChanged().model_dump(), status_code=status.HTTP_409_CONFLICT
        )
    except InvalidHealthFormError as refused:
        answer = HealthFormRefused(
            errors={field: "invalid" for field in refused.fields}
        )
        return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST)
    today = local_today()
    save_form(db, device.customer, checked, today=today)
    return status_answer(health_form_status(db, device.customer, today))


def _png_bytes(data_url: str) -> bytes:
    """The PNG inside a data URL; empty (refused as a bad signature) when
    it isn't one."""
    if not data_url.startswith(_PNG_DATA_URL):
        return b""
    try:
        return base64.b64decode(data_url.removeprefix(_PNG_DATA_URL), validate=True)
    except binascii.Error:
        return b""
