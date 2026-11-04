"""The health form routes of the admin JSON API, on the real admin app:
the status every staff member sees, the manager's list, opening a form's
PDF, who may do what, and what's logged. Names are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import health_forms, pins
from app.core.activity_log import Action, Target
from app.core.db import get_engine
from app.core.health_forms import CURRENT_VERSION, expires_on
from app.core.models import ActivityLogEntry, Customer, HealthForm, StaffUser
from app.core.permissions import Role
from app.core.staff import create_first_manager, create_staff_user

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
    staff = create_first_manager(db, "מנהלת", PIN)
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
