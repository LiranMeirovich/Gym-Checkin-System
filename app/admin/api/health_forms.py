"""A customer's health forms as JSON (design doc: "Health form", "Validity
and access"; decisions 0004, 0031).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/customers/{id}/health-form``: valid, needs a doctor's note,
  or missing, and until when (``health_forms.view_status``, every role).
  Never the answers.
- ``GET /api/customers/{id}/health-forms``: every form the customer has
  signed, newest first, without their contents
  (``health_forms.view_contents``, the manager).
- ``POST /api/customers/{id}/health-forms/{form_id}/open``: the form's PDF
  (``health_forms.view_contents``). A POST, not a GET: every opening is
  written to the activity log, a GET must never change anything, and the
  CSRF header means no other site can make a browser open one. A form
  that isn't this customer's is a 404.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.admin.api.customers import NOT_FOUND, CustomerId, customer_or_404
from app.admin.api.schemas import (
    MAX_ID,
    HealthFormList,
    HealthFormStatus,
    HealthFormSummary,
    NotLoggedIn,
)
from app.admin.security import StaffLogin, require_permission
from app.core import health_forms
from app.core.db import DbSession
from app.core.permissions import Permission

router = APIRouter(
    prefix="/customers/{customer_id}",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
        **NOT_FOUND,
    },
)

CanViewStatus = Annotated[
    StaffLogin, Depends(require_permission(Permission.HEALTH_FORMS_VIEW_STATUS))
]
CanViewContents = Annotated[
    StaffLogin, Depends(require_permission(Permission.HEALTH_FORMS_VIEW_CONTENTS))
]
FormId = Annotated[int, Path(ge=1, le=MAX_ID)]


@router.get("/health-form")
def health_form_status(
    customer_id: CustomerId, db: DbSession, _login: CanViewStatus
) -> HealthFormStatus:
    customer = customer_or_404(db, customer_id)
    found = health_forms.health_form_status(db, customer, health_forms.local_today())
    return HealthFormStatus(state=found.state, valid_until=found.valid_until)


@router.get("/health-forms")
def health_form_list(
    customer_id: CustomerId, db: DbSession, _login: CanViewContents
) -> HealthFormList:
    customer = customer_or_404(db, customer_id)
    return HealthFormList(
        forms=[
            HealthFormSummary(
                id=form.id,
                form_version=form.form_version,
                signed_on=form.signed_on,
                expires_on=form.expires_on,
                signer_name=form.signer_name,
                signed_by_guardian=form.signed_by_guardian,
                needs_doctor_note=form.needs_doctor_note,
            )
            for form in health_forms.list_forms(db, customer)
        ]
    )


@router.post(
    "/health-forms/{form_id}/open",
    response_class=Response,
    responses={status.HTTP_200_OK: {"content": {"application/pdf": {}}}},
)
def open_health_form(
    customer_id: CustomerId, form_id: FormId, db: DbSession, login: CanViewContents
) -> Response:
    customer = customer_or_404(db, customer_id)
    form = health_forms.form_of(db, customer, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    document = health_forms.open_form_document(db, form, by=login.staff)
    return Response(
        document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="health-form-{form.id}.pdf"'
        },
    )
