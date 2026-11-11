"""The manual check-in route of the admin JSON API, on the real admin app:
each answer, the instructor's single-entry fallback, the manager's plan,
who may do what, and what's recorded. Names and amounts are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import checkins, months, pins, punch_cards
from app.core.db import get_engine
from app.core.models import (
    CheckIn,
    CheckInMethod,
    ChosenBy,
    Customer,
    HealthForm,
    Plan,
    PlanChoice,
    Price,
    PunchCard,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
# Midday on 15 November 2026, UTC (14:00 in Israel).
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(checkins, "utc_now", clock)
    monkeypatch.setattr(months, "utc_now", clock)
    monkeypatch.setattr(punch_cards, "utc_now", clock)
    return clock


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
def manager(db: Session) -> StaffUser:
    staff = create_owner(db, "מנהלת", PIN)
    db.commit()
    return staff


@pytest.fixture
def instructor(db: Session, manager: StaffUser) -> StaffUser:
    staff = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()
    return staff


@pytest.fixture
def customer(db: Session) -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1990, 5, 1),
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def valid_form(db: Session, customer: Customer) -> None:
    add_form(db, customer)


@pytest.fixture
def prices(db: Session) -> None:
    """Every price, set from before this month."""
    for plan, amount in {
        Plan.MONTHLY: 25000,
        Plan.TRI_MONTHLY: 65000,
        Plan.SINGLE_ENTRY: 4000,
    }.items():
        db.add(
            Price(
                plan=plan,
                amount_agorot=amount,
                valid_from_month=Month(2026, 1),
            )
        )
    db.commit()


def add_form(db: Session, customer: Customer, *, yes: bool = False) -> None:
    db.add(
        HealthForm(
            customer_id=customer.id,
            form_version="test",
            answers_json="{}",
            needs_doctor_note=yes,
            signer_name="Noa Levi",
            signed_by_guardian=False,
            signed_on=date(2026, 3, 1),
            expires_on=date(2027, 2, 28),
            document=b"%PDF-1.7 made up",
        )
    )
    db.commit()


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

    def check_in(self, customer_id: int, body: object = None, *, csrf: bool = True):
        return self.client.post(
            f"/api/customers/{customer_id}/check-in",
            json={} if body is None else body,
            headers=self.headers if csrf else SAME_ORIGIN,
        )


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


def recorded(db: Session) -> list[CheckIn]:
    db.rollback()
    return list(db.scalars(select(CheckIn).order_by(CheckIn.id)))


def choices(db: Session) -> list[PlanChoice]:
    db.rollback()
    return list(db.scalars(select(PlanChoice).order_by(PlanChoice.id)))


def test_not_logged_in_gets_401(client: TestClient, customer: Customer) -> None:
    response = client.post(
        f"/api/customers/{customer.id}/check-in", json={}, headers=SAME_ORIGIN
    )

    assert response.status_code == 401


def test_a_check_in_needs_the_csrf_token(
    as_instructor: Staff, db: Session, customer: Customer, valid_form: None
) -> None:
    assert as_instructor.check_in(customer.id, csrf=False).status_code == 403
    assert recorded(db) == []


def test_an_unknown_customer_is_404(as_instructor: Staff) -> None:
    assert as_instructor.check_in(999).status_code == 404


def test_an_instructor_checks_in_a_customer_with_no_plan_as_single_entry(
    as_instructor: Staff,
    db: Session,
    instructor: StaffUser,
    customer: Customer,
    valid_form: None,
    prices: None,
) -> None:
    response = as_instructor.check_in(customer.id)

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "checked_in",
        "checked_in_at": "2026-11-15T14:00:00+02:00",
        "plan": {
            "plan": "single_entry",
            "start_month": "2026-11",
            "end_month": "2026-11",
        },
        "punch_card": None,
    }
    [row] = recorded(db)
    assert row.method is CheckInMethod.MANUAL
    assert row.staff_user_id == instructor.id
    [choice] = choices(db)
    assert choice.staff_user_id == instructor.id


def test_an_instructor_sending_a_plan_is_403(
    as_instructor: Staff, db: Session, customer: Customer, valid_form: None
) -> None:
    response = as_instructor.check_in(customer.id, {"plan": "monthly"})

    assert response.status_code == 403
    assert response.json() == {"error": "plan_not_allowed"}
    assert recorded(db) == []


def test_the_manager_is_asked_for_a_plan_with_the_options(
    as_manager: Staff, db: Session, customer: Customer, valid_form: None, prices: None
) -> None:
    response = as_manager.check_in(customer.id)

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "plan_required"
    assert body["month"] == "2026-11"
    assert {
        "plan": "monthly",
        "amount_agorot": 25000,
    } in body["options"]
    assert recorded(db) == []


def test_the_manager_checks_in_with_a_plan(
    as_manager: Staff, db: Session, customer: Customer, valid_form: None, prices: None
) -> None:
    response = as_manager.check_in(customer.id, {"plan": "tri_monthly"})

    assert response.status_code == 200
    assert response.json()["plan"] == {
        "plan": "tri_monthly",
        "start_month": "2026-11",
        "end_month": "2027-01",
    }
    assert [choice.plan for choice in choices(db)] == [Plan.TRI_MONTHLY]


def test_no_health_form_is_409_with_its_status(
    as_instructor: Staff, db: Session, customer: Customer, prices: None
) -> None:
    response = as_instructor.check_in(customer.id)

    assert response.status_code == 409
    assert response.json() == {
        "error": "health_form_required",
        "health_form": {
            "state": "missing",
            "valid_until": None,
            "allows_check_in": False,
        },
    }
    assert recorded(db) == []
    assert choices(db) == []


def test_a_form_waiting_for_a_doctors_note_checks_in(
    as_instructor: Staff, db: Session, customer: Customer, prices: None
) -> None:
    add_form(db, customer, yes=True)

    response = as_instructor.check_in(customer.id)

    assert response.status_code == 200
    assert len(recorded(db)) == 1


def test_an_unset_price_is_409(
    as_instructor: Staff, db: Session, customer: Customer, valid_form: None
) -> None:
    response = as_instructor.check_in(customer.id)

    assert response.status_code == 409
    assert response.json() == {"error": "price_not_set"}
    assert recorded(db) == []


def test_an_inactive_customer_is_409(
    as_instructor: Staff, db: Session, customer: Customer, valid_form: None
) -> None:
    customer.active = False
    db.commit()

    response = as_instructor.check_in(customer.id)

    assert response.status_code == 409
    assert response.json() == {"error": "customer_inactive"}


def test_a_second_check_in_within_ten_minutes_is_already_checked_in(
    as_instructor: Staff,
    db: Session,
    customer: Customer,
    valid_form: None,
    prices: None,
    clock: Clock,
) -> None:
    as_instructor.check_in(customer.id)
    clock.now = NOW + timedelta(minutes=4)

    response = as_instructor.check_in(customer.id)

    assert response.status_code == 200
    assert response.json()["outcome"] == "already_checked_in"
    assert response.json()["checked_in_at"] == "2026-11-15T14:00:00+02:00"
    assert len(recorded(db)) == 1


# Punch cards at the desk (decision 0042)


def card_price(db: Session) -> None:
    db.add(
        Price(
            plan=Plan.PUNCH_CARD, amount_agorot=50000, valid_from_month=Month(2026, 1)
        )
    )
    db.commit()


def test_the_manager_sells_a_punch_card_with_the_check_in(
    as_manager: Staff, db: Session, customer: Customer, valid_form: None, prices: None
) -> None:
    card_price(db)
    refused = as_manager.check_in(customer.id)
    assert refused.status_code == 409
    assert refused.json()["options"][-1] == {
        "plan": "punch_card",
        "amount_agorot": 50000,
    }

    response = as_manager.check_in(customer.id, {"plan": "punch_card"})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["punch_card"] == {"entries_left": 19, "expires_on": "2027-01-01"}
    [row] = recorded(db)
    assert row.punch_card_id is not None
    assert choices(db) == []


def test_an_instructor_uses_the_active_card(
    as_instructor: Staff,
    db: Session,
    customer: Customer,
    valid_form: None,
    prices: None,
) -> None:
    # The customer bought a card on their phone earlier this month.
    db.add(
        PunchCard(
            customer_id=customer.id,
            price_agorot=50000,
            bought_month=Month(2026, 11),
            expires_on=date(2027, 1, 1),
            bought_by=ChosenBy.CUSTOMER,
        )
    )
    db.commit()

    response = as_instructor.check_in(customer.id)

    assert response.status_code == 200
    assert response.json()["plan"] is None
    assert response.json()["punch_card"] == {
        "entries_left": 19,
        "expires_on": "2027-01-01",
    }
    # Not single entry: the card paid.
    assert choices(db) == []
