"""A customer's health forms as JSON (design doc: "Health form", "Validity
and access"; decisions 0004, 0031).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/customers/{id}/health-form``: valid, needs a doctor's note,
  or missing, and until when (``health_forms.view_status``, every role).
  Never the answers.
- ``GET /api/customers/{id}/health-forms``: every form the customer has
  signed, newest first, with its doctor's notes' ids but without their
  contents (``health_forms.view_contents``, the manager).
- ``POST /api/customers/{id}/health-forms/{form_id}/open``: the form's PDF
  (``health_forms.view_contents``). A POST, not a GET: every opening is
  written to the activity log, a GET must never change anything, and the
  CSRF header means no other site can make a browser open one. A form
  that isn't this customer's is a 404.
- ``POST /api/customers/{id}/health-form/doctor-note``: add a doctor's
  note to the form that counts today, which must be waiting for one
  (``health_forms.add_doctor_note``, every role). The answer is the
  updated status. The image is checked before any database work, so a
  slow check never holds the write lock (decision 0027). 400
  ``invalid_image``; 409 ``no_note_needed`` or ``customer_inactive``.
- ``POST /api/customers/{id}/doctor-notes/{note_id}/open``: a note's image
  (``health_forms.view_contents``), logged like opening a form. A note
  that isn't this customer's is a 404.
"""

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse

from app.admin.api.customers import NOT_FOUND, CustomerId, customer_or_404
from app.admin.api.schemas import (
    MAX_ID,
    DoctorNoteConflict,
    DoctorNoteRefused,
    DoctorNoteRequest,
    HealthFormList,
    HealthFormStatus,
    HealthFormSummary,
    NotLoggedIn,
)
from app.admin.security import StaffLogin, require_permission
from app.core import doctor_notes, health_forms
from app.core.customers import CustomerInactiveError
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
CanAddDoctorNote = Annotated[
    StaffLogin, Depends(require_permission(Permission.HEALTH_FORMS_ADD_DOCTOR_NOTE))
]
FormId = Annotated[int, Path(ge=1, le=MAX_ID)]
NoteId = Annotated[int, Path(ge=1, le=MAX_ID)]

# What a browser's FileReader gives for a JPEG or PNG file.
_IMAGE_DATA_URLS = ("data:image/jpeg;base64,", "data:image/png;base64,")


def status_answer(found: health_forms.HealthFormStatus) -> HealthFormStatus:
    return HealthFormStatus(state=found.state, valid_until=found.valid_until)


@router.get("/health-form")
def health_form_status(
    customer_id: CustomerId, db: DbSession, _login: CanViewStatus
) -> HealthFormStatus:
    customer = customer_or_404(db, customer_id)
    return status_answer(
        health_forms.health_form_status(db, customer, health_forms.local_today())
    )


@router.get("/health-forms")
def health_form_list(
    customer_id: CustomerId, db: DbSession, _login: CanViewContents
) -> HealthFormList:
    customer = customer_or_404(db, customer_id)
    forms = health_forms.list_forms(db, customer)
    notes = doctor_notes.notes_by_form(db, forms)
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
                doctor_note_ids=notes[form.id],
            )
            for form in forms
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


@router.post(
    "/health-form/doctor-note",
    response_model=HealthFormStatus,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": DoctorNoteRefused},
        status.HTTP_409_CONFLICT: {"model": DoctorNoteConflict},
    },
)
def add_doctor_note(
    customer_id: CustomerId,
    body: DoctorNoteRequest,
    db: DbSession,
    login: CanAddDoctorNote,
) -> HealthFormStatus | JSONResponse:
    # Before any database work: the transaction takes the write lock with
    # its first query (decision 0027).
    try:
        image = doctor_notes.check_note_image(_image_bytes(body.image))
    except doctor_notes.InvalidNoteImageError:
        return JSONResponse(
            DoctorNoteRefused().model_dump(), status.HTTP_400_BAD_REQUEST
        )
    customer = customer_or_404(db, customer_id)
    today = health_forms.local_today()
    try:
        doctor_notes.add_doctor_note(db, customer, image, by=login.staff, today=today)
    except CustomerInactiveError:
        answer = DoctorNoteConflict(error="customer_inactive")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    except doctor_notes.NoNoteNeededError as refused:
        answer = DoctorNoteConflict(error="no_note_needed", state=refused.state)
        return JSONResponse(answer.model_dump(mode="json"), status.HTTP_409_CONFLICT)
    return status_answer(health_forms.health_form_status(db, customer, today))


@router.post(
    "/doctor-notes/{note_id}/open",
    response_class=Response,
    responses={status.HTTP_200_OK: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def open_doctor_note(
    customer_id: CustomerId, note_id: NoteId, db: DbSession, login: CanViewContents
) -> Response:
    customer = customer_or_404(db, customer_id)
    note = doctor_notes.note_of(db, customer, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    image = doctor_notes.open_doctor_note(db, note, by=login.staff)
    return Response(
        image,
        media_type=note.content_type.value,
        headers={"Content-Disposition": "inline"},
    )


def _image_bytes(data_url: str) -> bytes:
    """The image inside a JPEG or PNG data URL; empty (refused as a bad
    image) when it isn't one. The bytes' own format is checked after."""
    for prefix in _IMAGE_DATA_URLS:
        if data_url.startswith(prefix):
            try:
                return base64.b64decode(data_url.removeprefix(prefix), validate=True)
            except binascii.Error:
                return b""
    return b""
