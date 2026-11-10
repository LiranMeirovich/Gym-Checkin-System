"""The health form routes of the admin JSON API, on the real admin app:
the status every staff member sees, the manager's list, opening a form's
PDF, adding and opening a doctor's note, filling in the form on the PC,
who may do what, and what's logged. Names, answers and images are made
up."""

import base64
import io
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import health_forms, pins
from app.core.activity_log import Action, Target
from app.core.db import get_engine
from app.core.health_forms import CURRENT_VERSION, FORMS, expires_on
from app.core.models import (
    ActivityLogEntry,
    Customer,
    DoctorNote,
    HealthForm,
    HealthFormAcceptance,
    ImageType,
    StaffUser,
)
from app.core.permissions import Role
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
PDF = b"%PDF-1.7 made-up snapshot"
# Noon in Israel on 4 November 2026.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_forms, "utc_now", lambda: NOW)


@pytest.fixture
def client(migrated_db: Path) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    staff = create_owner(db, "מנהלת", PIN)
    db.commit()
    return staff


@pytest.fixture
def instructor(db: Session, manager: StaffUser) -> StaffUser:
    staff = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()
    return staff


def make_customer(db: Session, phone: str = "+972501234567") -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone=phone,
        date_of_birth=date(1990, 5, 1),
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def customer(db: Session) -> Customer:
    return make_customer(db)


def add_form(
    db: Session, customer: Customer, signed: date, *, yes: bool = False
) -> HealthForm:
    form = HealthForm(
        customer_id=customer.id,
        form_version=CURRENT_VERSION,
        answers_json="{}",
        needs_doctor_note=yes,
        signer_name="Noa Levi",
        signed_by_guardian=False,
        signed_on=signed,
        expires_on=expires_on(signed),
        document=PDF,
    )
    db.add(form)
    db.commit()
    return form


class Staff:
    """A logged-in browser: sends the CSRF token on every write."""

    def __init__(self, client: TestClient, member: StaffUser) -> None:
        self.client = client
        answer = client.post(
            "/api/login",
            json={"staff_id": member.id, "pin": PIN},
            headers=SAME_ORIGIN,
        )
        assert answer.status_code == 200
        self.headers = {**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]}

    def status(self, customer_id: int):
        return self.client.get(f"/api/customers/{customer_id}/health-form")

    def forms(self, customer_id: int):
        return self.client.get(f"/api/customers/{customer_id}/health-forms")

    def open(self, customer_id: int, form_id: int, *, csrf: bool = True):
        return self.client.post(
            f"/api/customers/{customer_id}/health-forms/{form_id}/open",
            headers=self.headers if csrf else SAME_ORIGIN,
        )


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


def opens_logged(db: Session) -> list[ActivityLogEntry]:
    return list(
        db.scalars(
            select(ActivityLogEntry).where(
                ActivityLogEntry.action == Action.HEALTH_FORM_OPEN
            )
        )
    )


# ── Not logged in ──────────────────────────────────────────────────────


def test_not_logged_in_gets_401(
    client: TestClient, db: Session, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4))

    assert client.get(f"/api/customers/{customer.id}/health-form").status_code == 401
    assert client.get(f"/api/customers/{customer.id}/health-forms").status_code == 401
    opened = client.post(
        f"/api/customers/{customer.id}/health-forms/{form.id}/open",
        headers=SAME_ORIGIN,
    )
    assert opened.status_code == 401


# ── Status: every staff member ─────────────────────────────────────────


def test_an_instructor_sees_the_status(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4))

    response = as_instructor.status(customer.id)

    assert response.status_code == 200
    assert response.json() == {"state": "valid", "valid_until": "2027-11-03"}


def test_a_yes_answer_shows_as_needing_a_doctors_note(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    assert as_instructor.status(customer.id).json()["state"] == "needs_doctor_note"


def test_no_form_shows_as_missing(as_instructor: Staff, customer: Customer) -> None:
    assert as_instructor.status(customer.id).json() == {
        "state": "missing",
        "valid_until": None,
    }


def test_an_unknown_customer_is_404(as_manager: Staff) -> None:
    assert as_manager.status(999).status_code == 404
    assert as_manager.forms(999).status_code == 404


# ── Contents: the manager only ─────────────────────────────────────────


def test_an_instructor_cant_list_or_open_forms(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4))

    assert as_instructor.forms(customer.id).status_code == 403
    assert as_instructor.open(customer.id, form.id).status_code == 403
    assert opens_logged(db) == []


def test_the_manager_lists_forms_newest_first(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    older = add_form(db, customer, date(2026, 1, 10))
    newer = add_form(db, customer, date(2026, 6, 1), yes=True)

    response = as_manager.forms(customer.id)

    assert response.status_code == 200
    forms = response.json()["forms"]
    assert [f["id"] for f in forms] == [newer.id, older.id]
    assert forms[0] == {
        "id": newer.id,
        "form_version": CURRENT_VERSION,
        "signed_on": "2026-06-01",
        "expires_on": "2027-05-31",
        "signer_name": "Noa Levi",
        "signed_by_guardian": False,
        "needs_doctor_note": True,
        "doctor_note_ids": [],
    }
    # Listing isn't opening.
    assert opens_logged(db) == []


def test_opening_a_form_returns_its_pdf_and_is_logged(
    as_manager: Staff, db: Session, manager: StaffUser, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4))

    response = as_manager.open(customer.id, form.id)

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    [entry] = opens_logged(db)
    assert entry.staff_user_id == manager.id
    assert (entry.target_type, entry.target_id) == (Target.HEALTH_FORM, form.id)


def test_opening_needs_the_csrf_token(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4))

    assert as_manager.open(customer.id, form.id, csrf=False).status_code == 403
    assert opens_logged(db) == []


def test_another_customers_form_is_404(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    other = make_customer(db, phone="+972521111111")
    form = add_form(db, other, date(2026, 11, 4))

    assert as_manager.open(customer.id, form.id).status_code == 404
    assert as_manager.open(customer.id, 999).status_code == 404
    assert opens_logged(db) == []


# Doctor's notes


def photo(fmt: str = "JPEG", size: tuple[int, int] = (800, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 180, 160)).save(out, format=fmt)
    return out.getvalue()


def data_url(image: bytes, kind: str = "jpeg") -> str:
    return f"data:image/{kind};base64," + base64.b64encode(image).decode()


def add_note(staff: Staff, customer_id: int, image: str, *, csrf: bool = True):
    return staff.client.post(
        f"/api/customers/{customer_id}/health-form/doctor-note",
        json={"image": image},
        headers=staff.headers if csrf else SAME_ORIGIN,
    )


def open_note(staff: Staff, customer_id: int, note_id: int):
    return staff.client.post(
        f"/api/customers/{customer_id}/doctor-notes/{note_id}/open",
        headers=staff.headers,
    )


def notes(db: Session) -> list[DoctorNote]:
    # A fresh read: see what the app committed since this session last read.
    db.rollback()
    return list(db.scalars(select(DoctorNote).order_by(DoctorNote.id)))


def logged(db: Session, action: Action) -> list[ActivityLogEntry]:
    db.rollback()
    return list(
        db.scalars(select(ActivityLogEntry).where(ActivityLogEntry.action == action))
    )


def test_an_instructor_adds_a_note_and_the_form_counts(
    as_instructor: Staff, db: Session, instructor: StaffUser, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4), yes=True)

    response = add_note(as_instructor, customer.id, data_url(photo()))

    assert response.status_code == 200
    assert response.json() == {"state": "valid", "valid_until": "2027-11-03"}
    [note] = notes(db)
    assert note.health_form_id == form.id
    assert note.staff_user_id == instructor.id
    assert note.content_type is ImageType.JPEG
    [entry] = logged(db, Action.HEALTH_FORM_ADD_DOCTOR_NOTE)
    assert entry.staff_user_id == instructor.id
    assert (entry.target_type, entry.target_id) == (Target.HEALTH_FORM, form.id)


def test_a_png_note_is_stored_as_a_jpeg(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    response = add_note(as_instructor, customer.id, data_url(photo("PNG"), "png"))

    assert response.status_code == 200
    [note] = notes(db)
    assert note.content_type is ImageType.JPEG
    assert note.image.startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize(
    "image",
    [
        "",
        "not a data url",
        "data:image/gif;base64,R0lGODlh",
        "data:image/jpeg;base64,not base64!",
        data_url(b"%PDF-1.7 not an image"),
        data_url(photo(size=(50, 50))),
    ],
)
def test_a_bad_image_is_refused(
    as_instructor: Staff, db: Session, customer: Customer, image: str
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    response = add_note(as_instructor, customer.id, image)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_image"}
    assert notes(db) == []


@pytest.mark.parametrize(("yes", "state"), [(False, "valid"), (None, "missing")])
def test_a_note_is_refused_when_none_is_needed(
    as_instructor: Staff,
    db: Session,
    customer: Customer,
    yes: bool | None,
    state: str,
) -> None:
    if yes is not None:
        add_form(db, customer, date(2026, 11, 4), yes=yes)

    response = add_note(as_instructor, customer.id, data_url(photo()))

    assert response.status_code == 409
    assert response.json() == {"error": "no_note_needed", "state": state}
    assert notes(db) == []


def test_a_note_for_an_inactive_customer_is_refused(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)
    customer.active = False
    db.commit()

    response = add_note(as_instructor, customer.id, data_url(photo()))

    assert response.status_code == 409
    assert response.json()["error"] == "customer_inactive"


def test_adding_a_note_needs_the_csrf_token(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    assert (
        add_note(as_instructor, customer.id, data_url(photo()), csrf=False).status_code
        == 403
    )
    assert notes(db) == []


def test_a_note_for_an_unknown_customer_is_404(as_instructor: Staff) -> None:
    assert add_note(as_instructor, 999, data_url(photo())).status_code == 404


# ── Accepting a form without a note (decision 0041) ───────────────────


def accept(staff: Staff, customer_id: int, *, csrf: bool = True):
    return staff.client.post(
        f"/api/customers/{customer_id}/health-form/accept",
        headers=staff.headers if csrf else SAME_ORIGIN,
    )


def acceptances(db: Session) -> list[HealthFormAcceptance]:
    db.rollback()
    return list(db.scalars(select(HealthFormAcceptance)))


def test_the_manager_accepts_a_form_and_it_counts(
    as_manager: Staff, db: Session, manager: StaffUser, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4), yes=True)

    response = accept(as_manager, customer.id)

    assert response.status_code == 200
    assert response.json() == {"state": "valid", "valid_until": "2027-11-03"}
    [accepted] = acceptances(db)
    assert (accepted.health_form_id, accepted.staff_user_id) == (form.id, manager.id)
    [entry] = logged(db, Action.HEALTH_FORM_ACCEPT)
    assert entry.staff_user_id == manager.id
    assert (entry.target_type, entry.target_id) == (Target.HEALTH_FORM, form.id)
    # Reviewed: no note is wanted any more.
    assert add_note(as_manager, customer.id, data_url(photo())).status_code == 409


def test_an_instructor_cant_accept_a_form(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    assert accept(as_instructor, customer.id).status_code == 403
    assert acceptances(db) == []


@pytest.mark.parametrize(("yes", "state"), [(False, "valid"), (None, "missing")])
def test_accepting_is_refused_when_nothing_waits(
    as_manager: Staff,
    db: Session,
    customer: Customer,
    yes: bool | None,
    state: str,
) -> None:
    if yes is not None:
        add_form(db, customer, date(2026, 11, 4), yes=yes)

    response = accept(as_manager, customer.id)

    assert response.status_code == 409
    assert response.json() == {"error": "no_note_needed", "state": state}
    assert acceptances(db) == []


def test_accepting_twice_is_refused(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)
    assert accept(as_manager, customer.id).status_code == 200

    response = accept(as_manager, customer.id)

    assert response.status_code == 409
    assert response.json() == {"error": "no_note_needed", "state": "valid"}
    assert len(acceptances(db)) == 1


def test_accepting_for_an_inactive_customer_is_refused(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)
    customer.active = False
    db.commit()

    response = accept(as_manager, customer.id)

    assert response.status_code == 409
    assert response.json()["error"] == "customer_inactive"
    assert acceptances(db) == []


def test_accepting_needs_the_csrf_token(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    assert accept(as_manager, customer.id, csrf=False).status_code == 403
    assert accept(as_manager, 999).status_code == 404
    assert acceptances(db) == []


def test_the_manager_sees_and_opens_a_note_and_opening_is_logged(
    as_manager: Staff, db: Session, manager: StaffUser, customer: Customer
) -> None:
    # One test client holds one login, so the manager adds the note too.
    form = add_form(db, customer, date(2026, 11, 4), yes=True)
    add_note(as_manager, customer.id, data_url(photo()))
    [note] = notes(db)

    [listed] = as_manager.forms(customer.id).json()["forms"]
    response = open_note(as_manager, customer.id, note.id)

    assert listed["id"] == form.id
    assert listed["doctor_note_ids"] == [note.id]
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == note.image
    [entry] = logged(db, Action.DOCTOR_NOTE_OPEN)
    assert entry.staff_user_id == manager.id
    assert (entry.target_type, entry.target_id) == (Target.DOCTOR_NOTE, note.id)


def test_an_instructor_cant_open_a_note(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)
    add_note(as_instructor, customer.id, data_url(photo()))
    [note] = notes(db)

    assert open_note(as_instructor, customer.id, note.id).status_code == 403
    assert logged(db, Action.DOCTOR_NOTE_OPEN) == []


def test_another_customers_note_is_404(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    other = make_customer(db, phone="+972521111111")
    add_form(db, other, date(2026, 11, 4), yes=True)
    add_note(as_manager, other.id, data_url(photo()))
    [note] = notes(db)

    assert open_note(as_manager, customer.id, note.id).status_code == 404
    assert open_note(as_manager, customer.id, 999).status_code == 404
    assert logged(db, Action.DOCTOR_NOTE_OPEN) == []


# ── Filling in the form on the PC ──────────────────────────────────────

ALL_NO = {q.key: False for q in FORMS[CURRENT_VERSION].questions}


def signature_data_url() -> str:
    image = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(20, 100), (100, 30), (180, 90)], "black", 5)
    out = io.BytesIO()
    image.save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


SIGNATURE = signature_data_url()


def filled_in(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "version": CURRENT_VERSION,
        "answers": ALL_NO,
        "details": {},
        "gender": "female",
        "signer_name": "Noa Levi",
        "confirmed": True,
        "signature": SIGNATURE,
    }
    return fields | changes


def form_to_fill_in(staff: Staff, customer_id: int):
    return staff.client.get(f"/api/customers/{customer_id}/health-form/fill-in")


def sign(staff: Staff, customer_id: int, *, csrf: bool = True, **changes: object):
    return staff.client.post(
        f"/api/customers/{customer_id}/health-form/fill-in",
        json=filled_in(**changes),
        headers=staff.headers if csrf else SAME_ORIGIN,
    )


def saved_forms(db: Session) -> list[HealthForm]:
    db.rollback()
    return list(db.scalars(select(HealthForm).order_by(HealthForm.id)))


def test_not_logged_in_cant_fill_in(client: TestClient, customer: Customer) -> None:
    url = f"/api/customers/{customer.id}/health-form/fill-in"

    assert client.get(url).status_code == 401
    assert client.post(url, json=filled_in(), headers=SAME_ORIGIN).status_code == 401


def test_an_instructor_gets_the_form_for_a_customer(
    as_instructor: Staff, customer: Customer
) -> None:
    response = form_to_fill_in(as_instructor, customer.id)

    assert response.status_code == 200
    page = response.json()
    assert page["version"] == CURRENT_VERSION
    assert page["customer_name"] == "Noa Levi"
    assert page["date_of_birth"] == "1990-05-01"
    assert page["phone"] == "050-1234567"
    assert [q["key"] for q in page["questions"]] == list(ALL_NO)
    assert page["guardian_consent"] is None
    assert page["valid_until_if_signed"] == expires_on(date(2026, 11, 4)).isoformat()


def test_an_under_18_gets_the_parents_consent(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    customer.date_of_birth = date(2010, 1, 1)
    db.commit()

    page = form_to_fill_in(as_instructor, customer.id).json()

    assert "Noa Levi" in page["guardian_consent"]


def test_signing_on_the_pc_makes_the_form_valid_and_is_logged(
    as_instructor: Staff, db: Session, instructor: StaffUser, customer: Customer
) -> None:
    response = sign(as_instructor, customer.id)

    assert response.status_code == 200
    assert response.json() == {
        "state": "valid",
        "valid_until": expires_on(date(2026, 11, 4)).isoformat(),
    }
    # The PC never becomes the customer's device.
    assert "set-cookie" not in response.headers
    [form] = saved_forms(db)
    assert form.customer_id == customer.id
    assert form.signer_name == "Noa Levi"
    assert form.document.startswith(b"%PDF")
    [entry] = logged(db, Action.HEALTH_FORM_FILL_IN)
    assert entry.staff_user_id == instructor.id
    assert entry.target_type == Target.HEALTH_FORM
    assert entry.target_id == form.id
    # Never the answers.
    assert json.loads(entry.after_json) == {"customer_id": customer.id}


def test_a_yes_answer_on_the_pc_needs_a_doctors_note(
    as_instructor: Staff, customer: Customer
) -> None:
    response = sign(as_instructor, customer.id, answers=ALL_NO | {"diabetes": True})

    assert response.status_code == 200
    assert response.json()["state"] == "needs_doctor_note"


def test_bad_fields_are_all_refused_and_nothing_is_saved(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    response = sign(
        as_instructor, customer.id, confirmed=False, signature="not a data url"
    )

    assert response.status_code == 400
    assert response.json() == {
        "errors": {"confirmed": "invalid", "signature": "invalid"}
    }
    assert saved_forms(db) == []
    assert logged(db, Action.HEALTH_FORM_FILL_IN) == []


def test_an_old_version_is_409(as_instructor: Staff, customer: Customer) -> None:
    response = sign(as_instructor, customer.id, version="2000-01")

    assert response.status_code == 409
    assert response.json() == {"error": "form_version_changed"}


def test_an_inactive_customer_cant_sign(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    customer.active = False
    db.commit()

    response = sign(as_instructor, customer.id)

    assert response.status_code == 409
    assert response.json() == {"error": "customer_inactive"}
    assert saved_forms(db) == []


def test_signing_on_the_pc_needs_the_csrf_token(
    as_instructor: Staff, db: Session, customer: Customer
) -> None:
    assert sign(as_instructor, customer.id, csrf=False).status_code == 403
    assert saved_forms(db) == []


def test_filling_in_for_an_unknown_customer_is_404(as_instructor: Staff) -> None:
    assert form_to_fill_in(as_instructor, 999).status_code == 404
    assert sign(as_instructor, 999).status_code == 404
