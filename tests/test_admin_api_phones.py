"""The linked-phone routes of the admin JSON API, on the real admin app:
issuing a link code, listing and unlinking a customer's phones, who may do
it, and what's logged. Names and numbers are made up."""

import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins
from app.core.clock import to_local
from app.core.db import get_engine
from app.core.models import (
    ActivityLogEntry,
    Customer,
    DeviceSession,
    LinkCode,
    StaffUser,
)
from app.core.permissions import Role
from app.core.phone_links import find_device, link_phone
from app.core.staff import create_owner, create_staff_user
from app.core.staff_sessions import hash_token

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
UA = "Mozilla/5.0 (Linux; Android 15)"


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

    def issue(self, customer_id: int):
        return self.client.post(
            f"/api/customers/{customer_id}/link-code", headers=self.headers
        )

    def phones(self, customer_id: int):
        return self.client.get(f"/api/customers/{customer_id}/phones")

    def unlink(self, customer_id: int, phone_id: int):
        return self.client.post(
            f"/api/customers/{customer_id}/phones/{phone_id}/unlink",
            headers=self.headers,
        )


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


def link_with(db: Session, code: str, phone: str = "0501234567") -> str:
    """Link a phone with ``code``, as the customer would; returns its
    token."""
    token = link_phone(db, phone=phone, code=code, user_agent=UA).token
    db.commit()
    return token


def log_entries(db: Session, action: str) -> list[ActivityLogEntry]:
    # Ends this session's read transaction, so it sees what the requests
    # committed since.
    db.rollback()
    return list(
        db.scalars(select(ActivityLogEntry).where(ActivityLogEntry.action == action))
    )


# Issuing a code


@pytest.mark.parametrize("role", ["manager", "instructor"])
def test_staff_can_issue_a_link_code(
    request: pytest.FixtureRequest, db: Session, customer: Customer, role: str
) -> None:
    staff: Staff = request.getfixturevalue(f"as_{role}")

    response = staff.issue(customer.id)

    assert response.status_code == 201
    answer = response.json()
    assert len(answer["code"]) == 6 and answer["code"].isdigit()
    expires_at = datetime.fromisoformat(answer["expires_at"])
    # The gym's local time, with its offset (+02:00 or +03:00 in summer).
    assert expires_at.utcoffset() == to_local(expires_at).utcoffset()
    assert response.headers["cache-control"] == "no-store"
    row = db.scalars(select(LinkCode)).one()
    assert row.code_hash == hash_token(answer["code"])


def test_issuing_is_logged_under_the_staff_member(
    db: Session, as_instructor: Staff, instructor: StaffUser, customer: Customer
) -> None:
    code = as_instructor.issue(customer.id).json()["code"]

    (entry,) = log_entries(db, "phone.issue_code")
    assert entry.staff_user_id == instructor.id
    assert (entry.target_type, entry.target_id) == ("customer", customer.id)
    assert code not in entry.after_json


def test_the_issued_code_links_a_phone(
    db: Session, as_manager: Staff, customer: Customer
) -> None:
    code = as_manager.issue(customer.id).json()["code"]

    token = link_with(db, code)

    assert find_device(db, token) is not None


def test_an_inactive_customer_gets_no_code(
    db: Session, as_manager: Staff, customer: Customer
) -> None:
    customer.active = False
    db.commit()

    response = as_manager.issue(customer.id)

    assert response.status_code == 409
    assert response.json() == {"error": "customer_inactive", "customer_id": None}
    assert db.scalars(select(LinkCode)).all() == []


def test_an_unknown_customer_is_a_404(as_manager: Staff) -> None:
    assert as_manager.issue(999).status_code == 404


def test_issuing_needs_a_login(client: TestClient, customer: Customer) -> None:
    response = client.post(
        f"/api/customers/{customer.id}/link-code", headers=SAME_ORIGIN
    )

    assert response.status_code == 401


def test_issuing_needs_the_csrf_token(
    db: Session, as_manager: Staff, client: TestClient, customer: Customer
) -> None:
    response = client.post(
        f"/api/customers/{customer.id}/link-code", headers=SAME_ORIGIN
    )

    assert response.status_code == 403
    assert db.scalars(select(LinkCode)).all() == []


# Listing phones


def test_a_customer_without_phones_has_an_empty_list(
    as_instructor: Staff, customer: Customer
) -> None:
    response = as_instructor.phones(customer.id)

    assert response.status_code == 200
    assert response.json() == {"phones": []}


def test_the_list_shows_each_live_phone(
    db: Session, as_instructor: Staff, customer: Customer
) -> None:
    link_with(db, as_instructor.issue(customer.id).json()["code"])

    (phone,) = as_instructor.phones(customer.id).json()["phones"]

    device = db.scalars(select(DeviceSession)).one()
    assert phone["id"] == device.id
    assert phone["user_agent"] == UA
    assert datetime.fromisoformat(phone["linked_at"]).utcoffset() is not None
    assert phone["last_used_at"] == phone["linked_at"]
    # Never the token or its hash.
    assert set(phone) == {"id", "user_agent", "linked_at", "last_used_at"}


def test_the_list_shows_only_this_customers_phones(
    db: Session, as_manager: Staff, customer: Customer
) -> None:
    other = make_customer(db, phone="+972521112233")
    link_with(db, as_manager.issue(other.id).json()["code"], phone="0521112233")

    assert as_manager.phones(customer.id).json() == {"phones": []}
    assert len(as_manager.phones(other.id).json()["phones"]) == 1


def test_listing_needs_a_login(client: TestClient, customer: Customer) -> None:
    assert client.get(f"/api/customers/{customer.id}/phones").status_code == 401


def test_listing_an_unknown_customer_is_a_404(as_manager: Staff) -> None:
    assert as_manager.phones(999).status_code == 404


# Unlinking


@pytest.mark.parametrize("role", ["manager", "instructor"])
def test_staff_can_unlink_a_phone(
    request: pytest.FixtureRequest, db: Session, customer: Customer, role: str
) -> None:
    staff: Staff = request.getfixturevalue(f"as_{role}")
    token = link_with(db, staff.issue(customer.id).json()["code"])
    device_id = db.scalars(select(DeviceSession.id)).one()

    response = staff.unlink(customer.id, device_id)

    assert response.status_code == 200
    assert response.json() == {"phones": []}
    db.rollback()
    assert find_device(db, token) is None


def test_unlinking_is_logged(
    db: Session, as_manager: Staff, manager: StaffUser, customer: Customer
) -> None:
    link_with(db, as_manager.issue(customer.id).json()["code"])
    device_id = db.scalars(select(DeviceSession.id)).one()

    as_manager.unlink(customer.id, device_id)

    (entry,) = log_entries(db, "phone.unlink")
    assert entry.staff_user_id == manager.id
    assert (entry.target_type, entry.target_id) == ("device_session", device_id)
    assert json.loads(entry.after_json) == {
        "customer_id": customer.id,
        "revoked": True,
    }


def test_unlinking_twice_changes_nothing(
    db: Session, as_manager: Staff, customer: Customer
) -> None:
    link_with(db, as_manager.issue(customer.id).json()["code"])
    device_id = db.scalars(select(DeviceSession.id)).one()
    as_manager.unlink(customer.id, device_id)

    response = as_manager.unlink(customer.id, device_id)

    assert response.status_code == 200
    assert len(log_entries(db, "phone.unlink")) == 1


def test_another_customers_phone_is_a_404(
    db: Session, as_manager: Staff, customer: Customer
) -> None:
    other = make_customer(db, phone="+972521112233")
    token = link_with(db, as_manager.issue(other.id).json()["code"], "0521112233")
    device_id = db.scalars(select(DeviceSession.id)).one()

    response = as_manager.unlink(customer.id, device_id)

    assert response.status_code == 404
    db.rollback()
    assert find_device(db, token) is not None


def test_an_unknown_phone_is_a_404(as_manager: Staff, customer: Customer) -> None:
    assert as_manager.unlink(customer.id, 999).status_code == 404


def test_unlinking_needs_the_csrf_token(
    db: Session, as_manager: Staff, client: TestClient, customer: Customer
) -> None:
    token = link_with(db, as_manager.issue(customer.id).json()["code"])
    device_id = db.scalars(select(DeviceSession.id)).one()

    response = client.post(
        f"/api/customers/{customer.id}/phones/{device_id}/unlink",
        headers=SAME_ORIGIN,
    )

    assert response.status_code == 403
    db.rollback()
    assert find_device(db, token) is not None
