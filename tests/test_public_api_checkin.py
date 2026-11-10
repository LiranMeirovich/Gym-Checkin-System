"""The public app's check-in route: each answer, choosing a plan with the
check-in, and refreshing the gym_device cookie. The rules themselves are
tested in test_checkins.py. Names, numbers and amounts are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import checkins, health_forms, months, phone_links
from app.core.db import get_engine
from app.core.health_forms import expires_on
from app.core.models import (
    CheckIn,
    ChosenBy,
    Customer,
    DeviceSession,
    HealthForm,
    Plan,
    PlanChoice,
    Price,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.phone_links import issue_link_code
from app.core.staff_sessions import hash_token
from app.public.device import DEVICE_COOKIE
from app.public.main import app as public_app

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
ORIGIN = "https://checkin.example.com"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
# Long before any month the tests run in.
EARLY_MONTH = Month(2020, 1)
FAKE_PDF = b"%PDF-1.4 made up"
# Midday on 15 November 2026, UTC (14:00 in Israel): far from any day or
# month boundary, so a slow run can't cross one.
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
TODAY = date(2026, 11, 15)
THIS_MONTH = Month(2026, 11)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (checkins, health_forms, months, phone_links):
        monkeypatch.setattr(module, "utc_now", lambda: NOW)


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(public_app, base_url=ORIGIN) as client:
        yield client


@pytest.fixture
def customer(db: Session) -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1995, 5, 17),
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def linked(client: TestClient, db: Session, customer: Customer) -> TestClient:
    """The client, as a phone linked to ``customer``."""
    staff = StaffUser(display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH)
    db.add(staff)
    db.commit()
    code = issue_link_code(db, customer, by=staff).code
    db.commit()
    response = client.post(
        "/api/link",
        json={"phone": "0501234567", "code": code},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def valid_form(db: Session, customer: Customer) -> None:
    add_form(db, customer)


@pytest.fixture
def prices(db: Session) -> None:
    amounts = {Plan.MONTHLY: 25000, Plan.TRI_MONTHLY: 65000, Plan.SINGLE_ENTRY: 4000}
    for plan, amount in amounts.items():
        db.add(Price(plan=plan, amount_agorot=amount, valid_from_month=EARLY_MONTH))
    db.commit()


def add_form(db: Session, customer: Customer, *, needs_doctor_note: bool = False):
    today = TODAY
    db.add(
        HealthForm(
            customer_id=customer.id,
            form_version="test",
            answers_json="{}",
            needs_doctor_note=needs_doctor_note,
            signer_name="Noa Levi",
            signed_by_guardian=False,
            signed_on=today,
            expires_on=expires_on(today),
            document=FAKE_PDF,
        )
    )
    db.commit()


def add_monthly(db: Session, customer: Customer) -> None:
    month = THIS_MONTH
    db.add(
        PlanChoice(
            customer_id=customer.id,
            plan=Plan.MONTHLY,
            start_month=month,
            end_month=month,
            unit_price_agorot=25000,
            chosen_by=ChosenBy.CUSTOMER,
        )
    )
    db.commit()


def check_in(client: TestClient, plan: str | None = None):
    body = {} if plan is None else {"plan": plan}
    return client.post("/api/check-in", json=body, headers=SAME_ORIGIN)


def visits(db: Session) -> list[CheckIn]:
    return list(db.scalars(select(CheckIn)))


def test_a_covered_month_checks_in(
    linked: TestClient, db: Session, customer: Customer, valid_form: None
) -> None:
    add_monthly(db, customer)

    response = check_in(linked)

    assert response.status_code == 200
    answer = response.json()
    assert answer["outcome"] == "checked_in"
    month = "2026-11"
    assert answer["plan"] == {
        "plan": "monthly",
        "start_month": month,
        "end_month": month,
    }
    [visit] = visits(db)
    assert visit.customer_id == customer.id
    assert visit.method == "phone"


def test_a_check_in_refreshes_the_device_cookie(
    linked: TestClient, db: Session, customer: Customer, valid_form: None
) -> None:
    add_monthly(db, customer)
    token = linked.cookies[DEVICE_COOKIE]

    response = check_in(linked)

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{DEVICE_COOKIE}={token};")
    flags = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= flags
    assert "max-age=31536000" in flags
    # The same session, still the one in use.
    device = db.scalar(
        select(DeviceSession).where(DeviceSession.token_hash == hash_token(token))
    )
    assert device is not None and device.revoked_at is None


def test_a_second_check_in_is_already_checked_in(
    linked: TestClient, db: Session, customer: Customer, valid_form: None
) -> None:
    add_monthly(db, customer)
    first = check_in(linked).json()

    again = check_in(linked)

    assert again.status_code == 200
    assert again.json()["outcome"] == "already_checked_in"
    assert again.json()["checked_in_at"] == first["checked_in_at"]
    assert len(visits(db)) == 1


def test_an_unlinked_phone_is_not_linked(client: TestClient, db: Session) -> None:
    response = check_in(client)

    assert response.status_code == 401
    assert response.json() == {"detail": "not_linked"}
    assert visits(db) == []


def test_a_dead_cookie_is_dropped(client: TestClient) -> None:
    client.cookies.set(DEVICE_COOKIE, "not-a-real-token", domain="checkin.example.com")

    response = check_in(client)

    assert response.status_code == 401
    assert f'{DEVICE_COOKIE}=""' in response.headers["set-cookie"]


def test_no_form_is_health_form_required(
    linked: TestClient, db: Session, customer: Customer
) -> None:
    add_monthly(db, customer)

    response = check_in(linked)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "health_form_required",
        "health_form": {"state": "missing", "valid_until": None},
    }
    assert "set-cookie" not in response.headers
    assert visits(db) == []


def test_a_form_needing_a_doctors_note_checks_in_like_any_other(
    linked: TestClient, db: Session, customer: Customer
) -> None:
    # The phone shows plain success; the manager reviews the form
    # (decision 0041). Nor does the phone hear that it's waiting.
    add_monthly(db, customer)
    add_form(db, customer, needs_doctor_note=True)

    response = check_in(linked)

    assert response.status_code == 200
    assert response.json()["outcome"] == "checked_in"
    assert len(visits(db)) == 1
    assert linked.get("/api/me").json()["health_form"]["state"] == "valid"


def test_no_plan_is_plan_required_with_the_options(
    linked: TestClient, db: Session, valid_form: None
) -> None:
    # Only the monthly price is set.
    db.add(
        Price(
            plan=Plan.MONTHLY,
            amount_agorot=25000,
            valid_from_month=EARLY_MONTH,
        )
    )
    db.commit()

    response = check_in(linked)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "plan_required",
        "month": "2026-11",
        "options": [
            {"plan": "monthly", "price_agorot": 25000},
            {"plan": "tri_monthly", "price_agorot": None},
            {"plan": "single_entry", "price_agorot": None},
        ],
    }
    assert visits(db) == []


def test_choosing_a_plan_checks_in_with_it(
    linked: TestClient, db: Session, valid_form: None, prices: None
) -> None:
    response = check_in(linked, "tri_monthly")

    assert response.status_code == 200
    answer = response.json()
    assert answer["outcome"] == "checked_in"
    assert answer["plan"]["plan"] == "tri_monthly"
    assert answer["plan"]["end_month"] == "2027-01"
    [choice] = db.scalars(select(PlanChoice)).all()
    assert choice.chosen_by is ChosenBy.CUSTOMER
    assert len(visits(db)) == 1


def test_a_plan_without_a_price_is_price_not_set(
    linked: TestClient, db: Session, valid_form: None
) -> None:
    response = check_in(linked, "single_entry")

    assert response.status_code == 409
    assert response.json() == {"detail": "price_not_set"}
    assert db.scalars(select(PlanChoice)).all() == []
    assert visits(db) == []


@pytest.mark.parametrize("plan", ["weekly", 1, ""])
def test_an_unknown_plan_is_refused(
    linked: TestClient, db: Session, valid_form: None, plan: object
) -> None:
    response = linked.post("/api/check-in", json={"plan": plan}, headers=SAME_ORIGIN)

    assert response.status_code == 422
    assert visits(db) == []


def test_another_sites_post_is_refused(
    linked: TestClient, db: Session, customer: Customer, valid_form: None
) -> None:
    add_monthly(db, customer)

    response = linked.post(
        "/api/check-in",
        json={},
        headers={"Origin": "https://evil.example.com", "Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert visits(db) == []


def test_a_get_never_checks_in(
    linked: TestClient, db: Session, customer: Customer, valid_form: None
) -> None:
    add_monthly(db, customer)

    # The SPA catch-all answers any other /api path with a 404.
    assert linked.get("/api/check-in").status_code == 404
    assert visits(db) == []
