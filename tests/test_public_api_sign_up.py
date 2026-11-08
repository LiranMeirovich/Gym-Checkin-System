"""The public app's sign-up route: a new customer signing up on their own
phone (decision 0035). Names and numbers are made up."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import ActivityLogEntry, Customer, DeviceSession
from app.core.staff_sessions import hash_token
from app.public.device import DEVICE_COOKIE
from app.public.main import app as public_app

ORIGIN = "https://checkin.example.com"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"
DETAILS = {
    "first_name": "Yael",
    "last_name": "Mizrahi",
    "phone": "050-123-4567",
    "date_of_birth": "2001-03-09",
}


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(public_app, base_url=ORIGIN) as client:
        yield client


def post_sign_up(client: TestClient, **changes: object):
    return client.post(
        "/api/sign-up",
        json=DETAILS | changes,
        headers={**SAME_ORIGIN, "User-Agent": UA},
    )


def customers(db: Session) -> list[Customer]:
    db.expire_all()
    return list(db.scalars(select(Customer).order_by(Customer.id)))


def devices(db: Session) -> list[DeviceSession]:
    db.expire_all()
    return list(db.scalars(select(DeviceSession).order_by(DeviceSession.id)))


def make_customer(db: Session, *, active: bool = True) -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1995, 5, 17),
        active=active,
    )
    db.add(customer)
    db.commit()
    return customer


def test_signing_up_answers_like_linking(client: TestClient) -> None:
    response = post_sign_up(client)

    assert response.status_code == 200
    assert response.json() == {
        "first_name": "Yael",
        "health_form": {"state": "missing", "valid_until": None},
    }
    assert response.headers["cache-control"] == "no-store"


def test_signing_up_saves_the_customer_and_sets_the_cookie(
    db: Session, client: TestClient
) -> None:
    response = post_sign_up(client)

    (customer,) = customers(db)
    assert customer.phone == "+972501234567"
    assert customer.date_of_birth == date(2001, 3, 9)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{DEVICE_COOKIE}=")
    flags = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "secure", "samesite=lax", "path=/", "max-age=31536000"} <= (
        flags
    )
    (device,) = devices(db)
    assert device.customer_id == customer.id
    assert device.token_hash == hash_token(client.cookies[DEVICE_COOKIE])
    assert device.user_agent == UA
    assert db.scalars(select(ActivityLogEntry)).all() == []


def test_a_signed_up_phone_knows_whose_it_is(client: TestClient) -> None:
    post_sign_up(client)

    assert client.get("/api/me").json()["first_name"] == "Yael"


def test_the_next_step_is_the_health_form(client: TestClient) -> None:
    post_sign_up(client)

    response = client.post("/api/check-in", json={}, headers=SAME_ORIGIN)

    assert response.status_code == 409
    assert response.json()["detail"] == "health_form_required"


@pytest.mark.parametrize("active", [True, False])
def test_a_customers_number_is_refused_the_same_way(
    db: Session, client: TestClient, active: bool
) -> None:
    existing = make_customer(db, active=active)

    response = post_sign_up(client, phone="+972 50 123 4567")

    assert response.status_code == 409
    # Never which customer, and the same answer active or not.
    assert response.json() == {"detail": "phone_taken"}
    assert "set-cookie" not in response.headers
    assert [c.id for c in customers(db)] == [existing.id]
    assert customers(db)[0].active is active
    assert devices(db) == []


def test_every_invalid_field_is_named(db: Session, client: TestClient) -> None:
    response = post_sign_up(
        client,
        first_name=" ",
        last_name="",
        phone="12345",
        date_of_birth="2999-01-01",
    )

    assert response.status_code == 400
    assert response.json() == {
        "errors": {
            "first_name": "invalid",
            "last_name": "invalid",
            "phone": "invalid",
            "date_of_birth": "invalid",
        }
    }
    assert "set-cookie" not in response.headers
    assert customers(db) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"date_of_birth": "09/03/2001"},
        {"date_of_birth": 984096000},
        {"first_name": "x" * 201},
        {"notes": None, "phone": None},
    ],
)
def test_a_malformed_request_is_422(
    db: Session, client: TestClient, changes: dict[str, object]
) -> None:
    response = post_sign_up(client, **changes)

    assert response.status_code == 422
    assert customers(db) == []


def test_notes_cannot_be_set_from_the_phone(db: Session, client: TestClient) -> None:
    post_sign_up(client, notes="VIP")

    assert customers(db)[0].notes == ""


def test_signing_up_replaces_this_browsers_old_login(
    db: Session, client: TestClient
) -> None:
    post_sign_up(client)
    first = client.cookies[DEVICE_COOKIE]

    post_sign_up(client, phone="052-111-2233", first_name="Tamar")

    old, new = devices(db)
    assert old.token_hash == hash_token(first)
    assert old.revoked_at is not None
    assert new.revoked_at is None
    assert client.get("/api/me").json()["first_name"] == "Tamar"


def test_a_sign_up_form_on_another_site_is_refused(
    db: Session, client: TestClient
) -> None:
    response = client.post(
        "/api/sign-up",
        json=DETAILS,
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert customers(db) == []
