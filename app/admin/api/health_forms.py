"""A customer's health forms as JSON (design doc: "Health form", "Validity
and access"; decisions 0004, 0031).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/customers/{id}/health-form``: valid, needs a doctor's note,
  or missing, and until when (``health_forms.view_status``, every role).
  Never the answers. Only staff who review forms (``health_forms.accept``)
  see "needs a doctor's note"; to the rest a form waiting for review is
  valid, as it is for getting in (decision 0041).
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
- ``POST /api/customers/{id}/health-form/accept``: the manager accepts
  the form that counts today without a doctor's note; it must be waiting
  for one (``health_forms.accept``, decision 0041). Logged. The answer is
  the updated status; 409 ``no_note_needed`` or ``customer_inactive``.
- ``GET /api/customers/{id}/health-form/fill-in``: the current form's
  wording and the customer's details, for the customer to fill in and
  sign on the admin PC (``health_forms.fill_in``, every role). The PC
  never becomes the customer's device: no ``gym_device`` cookie here.
- ``POST /api/customers/{id}/health-form/fill-in``: the signed form, as
  on the phone (``health_forms.fill_in``), logged with the staff member
  (never the answers). The answer is the customer's status afterwards.
  The signature is checked before any database work (decision 0027).
  400 lists every bad field; 409 ``form_version_changed`` or
  ``customer_inactive``.
- ``POST /api/customers/{id}/doctor-notes/{note_id}/open``: a note's image
  (``health_forms.view_contents``), logged like opening a form. A note
  that isn't this customer's is a 404.

Across all customers (status and dates, never the answers). Only active
customers, each by the form that counts for them today:

- ``GET /api/health-forms/needing-note``: forms with a "yes" answer the
  manager hasn't reviewed yet (no doctor's note, not accepted), oldest
  signature first: the dashboard's "forms to review" (``health_forms.
  accept``, the manager; decision 0041).
- ``GET /api/health-forms/expiring``: valid forms whose last day is within
  30 days, soonest first (``health_forms.view_status``, every role). No
  screen uses it since decision 0041.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse

from app.admin.api.customers import NOT_FOUND, CustomerId, customer_or_404
from app.admin.api.schemas import (
    MAX_ID,
    CustomerFormEntry,
    CustomerForms,
    CustomerName,
    DoctorNoteConflict,
    DoctorNoteRefused,
    DoctorNoteRequest,
    HealthFormConflict,
    HealthFormList,
    HealthFormPage,
    HealthFormQuestion,
    HealthFormRefused,
    HealthFormRequest,
    HealthFormStatus,
    HealthFormSummary,
    NotLoggedIn,
)
from app.admin.security import StaffLogin, require_permission
from app.core import doctor_notes, health_forms
from app.core.clock import local_today
from app.core.customers import CustomerInactiveError
from app.core.db import DbSession
from app.core.http import JPEG_DATA_URL, PNG_DATA_URL, data_url_bytes
from app.core.permissions import Permission, has_permission

router = APIRouter(
    prefix="/customers/{customer_id}",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
        **NOT_FOUND,
    },
)

# Every customer's forms, not one customer's.
gym_router = APIRouter(
    prefix="/health-forms",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
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
CanAccept = Annotated[
    StaffLogin, Depends(require_permission(Permission.HEALTH_FORMS_ACCEPT))
]
CanFillIn = Annotated[
    StaffLogin, Depends(require_permission(Permission.HEALTH_FORMS_FILL_IN))
]
FormId = Annotated[int, Path(ge=1, le=MAX_ID)]
NoteId = Annotated[int, Path(ge=1, le=MAX_ID)]


def status_answer(found: health_forms.HealthFormStatus) -> HealthFormStatus:
    return HealthFormStatus(state=found.state, valid_until=found.valid_until)


def status_for(
    login: StaffLogin, found: health_forms.HealthFormStatus
) -> HealthFormStatus:
    """``found`` as ``login``'s staff member sees it: only those who review
    forms see one waiting for review (decision 0041)."""
    if not has_permission(login.staff.role, Permission.HEALTH_FORMS_ACCEPT):
        found = found.as_entry_status()
    return status_answer(found)


def customer_forms(found: list[health_forms.CustomerForm]) -> CustomerForms:
    return CustomerForms(
        forms=[
            CustomerFormEntry(
                customer=CustomerName.of(entry.customer),
                signed_on=entry.form.signed_on,
                valid_until=entry.form.expires_on,
            )
            for entry in found
        ]
    )


@gym_router.get("/needing-note")
def needing_doctor_note(db: DbSession, _login: CanAccept) -> CustomerForms:
    return customer_forms(health_forms.forms_needing_doctor_note(db, local_today()))


@gym_router.get("/expiring")
def expiring(db: DbSession, _login: CanViewStatus) -> CustomerForms:
    return customer_forms(health_forms.forms_expiring(db, local_today()))


@router.get("/health-form")
def health_form_status(
    customer_id: CustomerId, db: DbSession, login: CanViewStatus
) -> HealthFormStatus:
    customer = customer_or_404(db, customer_id)
    return status_for(
        login, health_forms.health_form_status(db, customer, health_forms.local_today())
    )


@router.get("/health-forms")
def health_form_list(
    customer_id: CustomerId, db: DbSession, _login: CanViewContents
) -> HealthFormList:
    customer = customer_or_404(db, customer_id)
    forms = health_forms.list_forms(db, customer)
    notes = doctor_notes.notes_by_form(db, forms)
    accepted = doctor_notes.accepted_forms(db, forms)
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
                accepted=form.id in accepted,
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


@router.get("/health-form/fill-in")
def health_form_to_fill_in(
    customer_id: CustomerId, db: DbSession, _login: CanFillIn
) -> HealthFormPage:
    customer = customer_or_404(db, customer_id)
    page = health_forms.form_page(db, customer, health_forms.local_today())
    form = page.form
    return HealthFormPage(
        version=form.version,
        title=form.title,
        customer_name=page.customer_name,
        date_of_birth=page.date_of_birth,
        phone=page.phone,
        wording_note=form.wording_note,
        part_a_title=form.part_a_title,
        part_a_notes=list(page.part_a_notes),
        questions_intro=form.questions_intro,
        questions=[
            HealthFormQuestion(key=q.key, text=q.text, has_details=q.has_details)
            for q in form.questions
        ],
        part_b_title=form.part_b_title,
        declaration=list(form.declaration),
        guardian_title=form.guardian_title,
        guardian_consent=page.guardian_consent,
        valid_until_if_signed=page.valid_until_if_signed,
    )


@router.post(
    "/health-form/fill-in",
    response_model=HealthFormStatus,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": HealthFormRefused},
        status.HTTP_409_CONFLICT: {"model": HealthFormConflict},
    },
)
def sign_health_form(
    customer_id: CustomerId,
    body: HealthFormRequest,
    db: DbSession,
    login: CanFillIn,
) -> HealthFormStatus | JSONResponse:
    # Before any database work: the transaction takes the write lock with
    # its first query (decision 0027).
    try:
        checked = health_forms.check_form(
            version=body.version,
            answers=body.answers,
            details=body.details,
            gender=body.gender,
            signer_name=body.signer_name,
            confirmed=body.confirmed,
            signature_png=data_url_bytes(body.signature, PNG_DATA_URL),
        )
    except health_forms.FormVersionChangedError:
        answer = HealthFormConflict(error="form_version_changed")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    except health_forms.InvalidHealthFormError as refused:
        answer = HealthFormRefused(
            errors={field: "invalid" for field in refused.fields}
        )
        return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST)
    customer = customer_or_404(db, customer_id)
    today = health_forms.local_today()
    try:
        health_forms.save_form(db, customer, checked, today=today, by=login.staff)
    except CustomerInactiveError:
        answer = HealthFormConflict(error="customer_inactive")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    return status_for(login, health_forms.health_form_status(db, customer, today))


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
        image = doctor_notes.check_note_image(
            data_url_bytes(body.image, JPEG_DATA_URL, PNG_DATA_URL)
        )
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
    return status_for(login, health_forms.health_form_status(db, customer, today))


@router.post(
    "/health-form/accept",
    response_model=HealthFormStatus,
    responses={status.HTTP_409_CONFLICT: {"model": DoctorNoteConflict}},
)
def accept_health_form(
    customer_id: CustomerId, db: DbSession, login: CanAccept
) -> HealthFormStatus | JSONResponse:
    customer = customer_or_404(db, customer_id)
    today = health_forms.local_today()
    try:
        doctor_notes.accept_form(db, customer, by=login.staff, today=today)
    except CustomerInactiveError:
        answer = DoctorNoteConflict(error="customer_inactive")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    except doctor_notes.NoNoteNeededError as refused:
        answer = DoctorNoteConflict(error="no_note_needed", state=refused.state)
        return JSONResponse(answer.model_dump(mode="json"), status.HTTP_409_CONFLICT)
    return status_for(login, health_forms.health_form_status(db, customer, today))


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
