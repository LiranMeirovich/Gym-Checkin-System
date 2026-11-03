"""The plan routes of the admin JSON API, on the real admin app: what each
role may do, the answers and error codes, and that refused requests save
nothing. Names and amounts are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import months, pins
from app.core.db import get_engine
from app.core.models import (
    ActivityLogEntry,
    AgeGroup,
    Customer,
    Plan,
    PlanChoice,
    Price,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.staff import create_first_manager, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
MONTHLY = {"plan": "monthly", "month": "2026-11"}


@pytest.fixture(autouse=True)
def fixed_month(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    )


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
    staff = create_first_manager(db, "מנהלת", PIN)
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
def prices(db: Session) -> None:
    """Every adult price, set from before this month. No under-18 ones."""
    for plan, amount in {
        Plan.MONTHLY: 25000,
        Plan.TRI_MONTHLY: 65000,
        Plan.SINGLE_ENTRY: 4000,
    }.items():
        db.add(
            Price(
                plan=plan,
                age_group=AgeGroup.ADULT,
                amount_agorot=amount,
                valid_from_month=Month(2026, 1),
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

    def get(self, customer_id: int):
        return self.client.get(f"/api/customers/{customer_id}/plan")

    def post(self, customer_id: int, json: object):
        return self.client.post(
            f"/api/customers/{customer_id}/plan", json=json, headers=self.headers
        )


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


def choices_in_db(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(PlanChoice))


# Who may do what


def test_not_logged_in_gets_401(client: TestClient, customer: Customer) -> None:
    url = f"/api/customers/{customer.id}/plan"
    assert client.get(url).status_code == 401
    assert client.post(url, json=MONTHLY, headers=SAME_ORIGIN).status_code == 401


def test_an_instructor_can_see_the_plan_status(
    as_instructor: Staff, customer: Customer
) -> None:
    assert as_instructor.get(customer.id).status_code == 200


def test_an_instructor_cant_choose_a_plan(
    as_instructor: Staff, customer: Customer, prices: None, db: Session
) -> None:
    assert as_instructor.post(customer.id, MONTHLY).status_code == 403
    assert choices_in_db(db) == 0


def test_a_choice_needs_the_csrf_token(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    answer = as_manager.client.post(
        f"/api/customers/{customer.id}/plan", json=MONTHLY, headers=SAME_ORIGIN
    )
    assert answer.status_code == 403
    assert choices_in_db(db) == 0


def test_an_unknown_customer_is_404(as_manager: Staff) -> None:
    assert as_manager.get(999).status_code == 404
    assert as_manager.post(999, MONTHLY).status_code == 404


# The answers


def test_nothing_chosen_yet(as_manager: Staff, customer: Customer) -> None:
    answer = as_manager.get(customer.id)

    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "no-store"
    assert answer.json() == {
        "current_month": "2026-11",
        "covering": None,
        "options": [
            {"plan": plan, "age_group": "adult", "amount_agorot": None}
            for plan in ("monthly", "tri_monthly", "single_entry")
        ],
        "history": [],
    }


def test_a_choice_answers_with_the_updated_status(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    answer = as_manager.post(customer.id, {"plan": "tri_monthly", "month": "2026-11"})

    assert answer.status_code == 201
    body = answer.json()
    covering = body["covering"]
    assert {k: v for k, v in covering.items() if k not in {"id", "chosen_at"}} == {
        "plan": "tri_monthly",
        "start_month": "2026-11",
        "end_month": "2027-01",
        "age_group": "adult",
        "unit_price_agorot": 65000,
        "chosen_by": "staff",
        "staff_name": "מנהלת",
        "replaces_id": None,
    }
    # The gym's local time, with its offset.
    chosen_at = datetime.fromisoformat(covering["chosen_at"])
    assert chosen_at.utcoffset() in {timedelta(hours=2), timedelta(hours=3)}
    assert body["history"] == [covering]
    assert [o["amount_agorot"] for o in body["options"]] == [25000, 65000, 4000]


def test_a_choice_is_logged_against_the_acting_manager(
    as_manager: Staff, manager: StaffUser, customer: Customer, prices: None, db: Session
) -> None:
    as_manager.post(customer.id, MONTHLY)

    entry = db.scalar(
        select(ActivityLogEntry).where(ActivityLogEntry.action == "plan.choose")
    )
    assert entry.staff_user_id == manager.id


def test_the_request_cannot_set_the_price(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    answer = as_manager.post(customer.id, {**MONTHLY, "unit_price_agorot": 1})

    assert answer.status_code == 201
    assert answer.json()["covering"]["unit_price_agorot"] == 25000


# Refusals


@pytest.mark.parametrize("month", ["2026-10", "2026-12"])
def test_another_month_is_refused(
    as_manager: Staff, customer: Customer, prices: None, db: Session, month: str
) -> None:
    answer = as_manager.post(customer.id, {**MONTHLY, "month": month})

    assert answer.status_code == 400
    assert answer.json() == {"error": "month_not_choosable"}
    assert choices_in_db(db) == 0


def test_an_unset_price_is_refused(
    as_manager: Staff, customer: Customer, db: Session
) -> None:
    answer = as_manager.post(customer.id, MONTHLY)

    assert answer.status_code == 400
    assert answer.json() == {"error": "price_not_set"}
    assert choices_in_db(db) == 0


def test_a_covered_month_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    first = as_manager.post(customer.id, MONTHLY).json()["covering"]

    answer = as_manager.post(customer.id, {**MONTHLY, "plan": "single_entry"})

    assert answer.status_code == 409
    assert answer.json() == {"error": "month_covered", "choice_id": first["id"]}
    assert choices_in_db(db) == 1


def test_an_inactive_customer_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    customer.active = False
    db.commit()

    answer = as_manager.post(customer.id, MONTHLY)

    assert answer.status_code == 409
    assert answer.json() == {"error": "customer_inactive", "choice_id": None}
    assert choices_in_db(db) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"plan": "weekly", "month": "2026-11"},
        {"plan": "monthly", "month": "2026-13"},
        {"plan": "monthly", "month": "2026-11-01"},
        {"plan": "monthly"},
        {"month": "2026-11"},
    ],
)
def test_a_malformed_request_is_422(
    as_manager: Staff, customer: Customer, prices: None, db: Session, body: object
) -> None:
    assert as_manager.post(customer.id, body).status_code == 422
    assert choices_in_db(db) == 0
