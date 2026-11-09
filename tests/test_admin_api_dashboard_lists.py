"""The dashboard's list routes on the real admin app: today's check-ins,
health forms needing a doctor's note or expiring, and the newest customers.
Who may read them and what each answer holds; the rules behind each list
are tested in ``test_dashboard_lists``. Names and numbers are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import health_forms, pins
from app.core.db import get_engine
from app.core.models import (
    CheckIn,
    CheckInMethod,
    Customer,
    HealthForm,
    StaffUser,
)
from app.core.permissions import Role
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
# Midday on 15 November 2026, UTC (14:00 in Israel, UTC+2).
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
TODAY = date(2026, 11, 15)
# Israel's 15 November starts at 22:00 UTC on the 14th.
DAY_START = datetime(2026, 11, 14, 22, 0, tzinfo=UTC)

LISTS = [
    "/api/checkins/today",
    "/api/health-forms/needing-note",
    "/api/health-forms/expiring",
    "/api/customers/latest",
]


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    # "Today" for every list comes from health_forms.local_today().
    monkeypatch.setattr(health_forms, "utc_now", lambda: NOW)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture
def client(migrated_db: Path) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def instructor(db: Session) -> StaffUser:
    manager = create_owner(db, "מנהלת", PIN)
    staff = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()
    return staff


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> TestClient:
    answer = client.post(
        "/api/login",
        json={"staff_id": instructor.id, "pin": PIN},
        headers=SAME_ORIGIN,
    )
    assert answer.status_code == 200
    return client


_numbers = iter(range(1_000_000))


def add_customer(
    db: Session,
    first_name: str,
    *,
    created_at: datetime = DAY_START - timedelta(days=100),
) -> Customer:
    customer = Customer(
        first_name=first_name,
        last_name="Levi",
        phone=f"+97250{next(_numbers):07d}",
        date_of_birth=date(1990, 5, 1),
        created_at=created_at,
    )
    db.add(customer)
    db.commit()
    return customer


def add_form(
    db: Session,
    customer: Customer,
    *,
    signed_on: date,
    expires_on: date,
    needs_doctor_note: bool = False,
) -> None:
    db.add(
        HealthForm(
            customer_id=customer.id,
            form_version="test",
            answers_json="{}",
            needs_doctor_note=needs_doctor_note,
            signer_name="Noa Levi",
            signed_by_guardian=False,
            signed_on=signed_on,
            expires_on=expires_on,
            document=b"%PDF-1.7 made up",
        )
    )
    db.commit()


def add_check_in(db: Session, customer: Customer, at: datetime, by: StaffUser) -> None:
    db.add(
        CheckIn(
            customer_id=customer.id,
            checked_in_at=at,
            method=CheckInMethod.MANUAL,
            staff_user_id=by.id,
        )
    )
    db.commit()


@pytest.mark.parametrize("path", LISTS)
def test_not_logged_in_gets_401(client: TestClient, path: str) -> None:
    answer = client.get(path)

    assert answer.status_code == 401


@pytest.mark.parametrize("path", LISTS)
def test_an_instructor_may_read_every_list(
    as_instructor: TestClient, path: str
) -> None:
    answer = as_instructor.get(path)

    assert answer.status_code == 200


def test_todays_check_ins_newest_first_with_who(
    db: Session, instructor: StaffUser, as_instructor: TestClient
) -> None:
    noa = add_customer(db, "Noa")
    dan = add_customer(db, "Dan")
    add_check_in(db, noa, DAY_START - timedelta(minutes=1), instructor)  # yesterday
    add_check_in(db, noa, DAY_START + timedelta(hours=8), instructor)
    add_check_in(db, dan, DAY_START + timedelta(hours=10), instructor)

    answer = as_instructor.get("/api/checkins/today").json()

    assert [
        (row["customer"]["first_name"], row["checked_in_at"])
        for row in answer["checkins"]
    ] == [
        ("Dan", "2026-11-15T10:00:00+02:00"),
        ("Noa", "2026-11-15T08:00:00+02:00"),
    ]
    assert answer["checkins"][0]["customer"] == {
        "id": dan.id,
        "first_name": "Dan",
        "last_name": "Levi",
    }
    assert answer["checkins"][0]["method"] == "manual"


def test_forms_needing_a_note_and_expiring(
    db: Session, as_instructor: TestClient
) -> None:
    waiting = add_customer(db, "Noa")
    add_form(
        db,
        waiting,
        signed_on=date(2026, 11, 1),
        expires_on=date(2027, 10, 31),
        needs_doctor_note=True,
    )
    ending = add_customer(db, "Dan")
    add_form(db, ending, signed_on=date(2025, 12, 10), expires_on=date(2026, 12, 9))
    fine = add_customer(db, "Maya")
    add_form(db, fine, signed_on=date(2026, 6, 1), expires_on=date(2027, 5, 31))

    needing = as_instructor.get("/api/health-forms/needing-note").json()
    expiring = as_instructor.get("/api/health-forms/expiring").json()

    assert needing == {
        "forms": [
            {
                "customer": {
                    "id": waiting.id,
                    "first_name": "Noa",
                    "last_name": "Levi",
                },
                "signed_on": "2026-11-01",
                "valid_until": "2027-10-31",
            }
        ]
    }
    assert expiring == {
        "forms": [
            {
                "customer": {"id": ending.id, "first_name": "Dan", "last_name": "Levi"},
                "signed_on": "2025-12-10",
                "valid_until": "2026-12-09",
            }
        ]
    }


def test_latest_customers_newest_first(db: Session, as_instructor: TestClient) -> None:
    older = add_customer(db, "Noa", created_at=DAY_START - timedelta(days=2))
    newer = add_customer(db, "Dan", created_at=DAY_START + timedelta(hours=9))

    answer = as_instructor.get("/api/customers/latest")

    # "latest" is its own route, not a customer id (that would be a 422).
    assert answer.status_code == 200
    customers = answer.json()["customers"]
    assert [row["id"] for row in customers] == [newer.id, older.id]
    assert customers[0] == {
        "id": newer.id,
        "first_name": "Dan",
        "last_name": "Levi",
        "phone": newer.phone,
        "active": True,
        "created_at": "2026-11-15T09:00:00+02:00",
    }
