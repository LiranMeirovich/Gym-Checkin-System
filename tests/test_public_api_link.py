"""The public app's link and me routes: linking a phone, the gym_device
cookie, and who a phone belongs to. Names and numbers are made up."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Customer, DeviceSession, StaffUser
from app.core.permissions import Role
from app.core.phone_links import issue_link_code, unlink
from app.core.staff_sessions import hash_token
from app.public.device import DEVICE_COOKIE
from app.public.main import app as public_app

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# The tunnel's https hostname, as a phone sees it.
ORIGIN = "https://checkin.example.com"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PHONE = "050-123-4567"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(public_app, base_url=ORIGIN) as client:
        yield client


@pytest.fixture
def staff(db: Session) -> StaffUser:
    member = StaffUser(
        display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH
    )
    db.add(member)
    db.commit()
    return member


def make_customer(db: Session, phone: str = "+972501234567") -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone=phone,
        date_of_birth=date(1995, 5, 17),
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def customer(db: Session) -> Customer:
    return make_customer(db)


def new_code(db: Session, customer: Customer, staff: StaffUser) -> str:
    code = issue_link_code(db, customer, by=staff).code
    db.commit()
    return code


def post_link(client: TestClient, code: str, phone: str = PHONE):
    return client.post(
        "/api/link",
        json={"phone": phone, "code": code},
        headers={**SAME_ORIGIN, "User-Agent": UA},
    )


def devices(db: Session) -> list[DeviceSession]:
    db.expire_all()
    return list(db.scalars(select(DeviceSession).order_by(DeviceSession.id)))


# Linking


def test_linking_answers_with_the_first_name_only(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    response = post_link(client, new_code(db, customer, staff))

    assert response.status_code == 200
    # Never the last name, phone or anything else.
    assert response.json() == {"first_name": "Noa"}
    assert response.headers["cache-control"] == "no-store"


def test_linking_sets_the_device_cookie(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    response = post_link(client, new_code(db, customer, staff))

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{DEVICE_COOKIE}=")
    flags = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= flags
    assert "max-age=31536000" in flags
    (device,) = devices(db)
    assert device.token_hash == hash_token(client.cookies[DEVICE_COOKIE])
    assert device.customer_id == customer.id
    assert device.user_agent == UA


def test_a_linked_phone_knows_whose_it_is(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    post_link(client, new_code(db, customer, staff))

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json() == {"first_name": "Noa"}


def test_a_wrong_code_is_refused_without_a_cookie(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    code = new_code(db, customer, staff)
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"

    response = post_link(client, wrong)

    assert response.status_code == 400
    assert response.json() == {"detail": "link_refused"}
    assert "set-cookie" not in response.headers
    assert devices(db) == []


@pytest.mark.parametrize("phone", ["0549998877", "not a number"])
def test_an_unknown_number_gets_the_same_refusal(
    db: Session,
    client: TestClient,
    customer: Customer,
    staff: StaffUser,
    phone: str,
) -> None:
    code = new_code(db, customer, staff)

    response = post_link(client, code, phone=phone)

    assert response.status_code == 400
    assert response.json() == {"detail": "link_refused"}


def test_a_code_works_once(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    code = new_code(db, customer, staff)
    post_link(client, code)
    client.cookies.clear()

    assert post_link(client, code).status_code == 400


def test_linking_again_replaces_this_browsers_login(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    post_link(client, new_code(db, customer, staff))
    old_token = client.cookies[DEVICE_COOKIE]

    post_link(client, new_code(db, customer, staff))

    first, second = devices(db)
    assert first.token_hash == hash_token(old_token)
    assert first.revoked_at is not None
    assert second.revoked_at is None
    assert client.get("/api/me").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"phone": PHONE},
        {"code": "123456"},
        {"phone": PHONE, "code": "1" * 21},
        {"phone": "0" * 51, "code": "123456"},
    ],
    ids=["no-code", "no-phone", "long-code", "long-phone"],
)
def test_a_malformed_request_is_a_422(client: TestClient, body: dict) -> None:
    response = client.post("/api/link", json=body, headers=SAME_ORIGIN)

    assert response.status_code == 422


def test_a_link_form_on_another_site_is_refused(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    response = client.post(
        "/api/link",
        json={"phone": PHONE, "code": new_code(db, customer, staff)},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert devices(db) == []


# Who a phone belongs to


def test_a_phone_without_a_cookie_is_not_linked(client: TestClient) -> None:
    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "not_linked"}
    assert "set-cookie" not in response.headers


def test_an_unlinked_phones_cookie_is_dropped(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    post_link(client, new_code(db, customer, staff))
    unlink(db, devices(db)[0], by=staff)
    db.commit()

    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.headers["set-cookie"].startswith(f'{DEVICE_COOKIE}=""')
    assert DEVICE_COOKIE not in client.cookies


def test_a_deactivated_customers_phone_is_not_linked(
    db: Session, client: TestClient, customer: Customer, staff: StaffUser
) -> None:
    post_link(client, new_code(db, customer, staff))
    customer.active = False
    db.commit()

    assert client.get("/api/me").status_code == 401


def test_a_made_up_cookie_is_not_linked(client: TestClient) -> None:
    client.cookies.set(DEVICE_COOKIE, "made-up")

    assert client.get("/api/me").status_code == 401
