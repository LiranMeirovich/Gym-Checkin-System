"""The customer routes of the admin JSON API, on the real admin app: what
each role may do, the answers and error codes, and that refused requests
save nothing. Names and phone numbers are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, Customer, StaffUser
from app.core.permissions import Role
from app.core.staff import create_first_manager, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
NOA = {
    "first_name": "נועה",
    "last_name": "לוי",
    "phone": "050-123 4567",
    "date_of_birth": "2001-05-17",
}


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

    def get(self, path: str, **kwargs):
        return self.client.get(path, **kwargs)

    def send(self, method: str, path: str, json: object = None):
        return self.client.request(method, path, json=json, headers=self.headers)


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


@pytest.fixture
def noa_id(as_manager: Staff) -> int:
    answer = as_manager.send("POST", "/api/customers", NOA)
    assert answer.status_code == 201
    return answer.json()["customer"]["id"]


def customers_in_db(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Customer))


def log_actions(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(ActivityLogEntry.action)
            .where(ActivityLogEntry.target_type == "customer")
            .order_by(ActivityLogEntry.id)
        )
    )


# ── Who may do what ─────────────────────────────────────────────────────


def test_every_customer_route_needs_a_login(
    client: TestClient, manager: StaffUser
) -> None:
    requests = [
        ("GET", "/api/customers"),
        ("GET", "/api/customers/1"),
        ("POST", "/api/customers"),
        ("PATCH", "/api/customers/1"),
        ("PUT", "/api/customers/1/date-of-birth"),
        ("POST", "/api/customers/1/deactivate"),
        ("POST", "/api/customers/1/reactivate"),
    ]
    for method, path in requests:
        answer = client.request(method, path, json={}, headers=SAME_ORIGIN)
        assert answer.status_code == 401, (method, path)
        assert answer.json()["detail"] == "not_logged_in"


def test_writes_need_the_csrf_token(as_manager: Staff, noa_id: int) -> None:
    answer = as_manager.client.patch(
        f"/api/customers/{noa_id}", json={"notes": "x"}, headers=SAME_ORIGIN
    )
    assert answer.status_code == 403


def test_an_instructor_can_view_add_edit_and_reactivate(
    db: Session, as_instructor: Staff
) -> None:
    added = as_instructor.send("POST", "/api/customers", NOA)
    assert added.status_code == 201
    noa_id = added.json()["customer"]["id"]

    assert as_instructor.get("/api/customers").status_code == 200
    assert as_instructor.get(f"/api/customers/{noa_id}").status_code == 200
    edited = as_instructor.send("PATCH", f"/api/customers/{noa_id}", {"notes": "חדשה"})
    assert edited.status_code == 200
    reactivated = as_instructor.send("POST", f"/api/customers/{noa_id}/reactivate")
    assert reactivated.status_code == 200


def test_an_instructor_cant_change_a_date_of_birth_or_deactivate(
    db: Session, as_instructor: Staff, noa_id: int
) -> None:
    birth = as_instructor.send(
        "PUT", f"/api/customers/{noa_id}/date-of-birth", {"date_of_birth": "2010-01-01"}
    )
    deactivated = as_instructor.send("POST", f"/api/customers/{noa_id}/deactivate")

    assert birth.status_code == 403
    assert deactivated.status_code == 403
    customer = db.get(Customer, noa_id)
    assert customer.date_of_birth.isoformat() == "2001-05-17"
    assert customer.active
    assert log_actions(db) == ["customer.create"]


# ── Adding ──────────────────────────────────────────────────────────────


def test_adding_answers_with_the_stored_customer(
    db: Session, as_manager: Staff, manager: StaffUser
) -> None:
    answer = as_manager.send("POST", "/api/customers", {**NOA, "notes": " מתחילה "})

    assert answer.status_code == 201
    body = answer.json()
    assert body["reactivated"] is False
    customer = body["customer"]
    assert customer["phone"] == "+972501234567"
    assert customer["notes"] == "מתחילה"
    assert customer["date_of_birth"] == "2001-05-17"
    assert customer["active"] is True
    # Local time with its offset (Israel: +02:00 or +03:00).
    assert customer["created_at"][-6:] in ("+02:00", "+03:00")
    entry = db.scalars(
        select(ActivityLogEntry).where(ActivityLogEntry.action == "customer.create")
    ).one()
    assert entry.staff_user_id == manager.id


def test_a_bad_form_names_every_field_and_saves_nothing(
    db: Session, as_manager: Staff
) -> None:
    answer = as_manager.send(
        "POST",
        "/api/customers",
        {
            "first_name": "",
            "last_name": "x" * 51,
            "phone": "123",
            "date_of_birth": "2999-01-01",
            "notes": "x" * 257,
        },
    )

    assert answer.status_code == 400
    assert answer.json() == {
        "errors": {
            "first_name": "invalid",
            "last_name": "invalid",
            "phone": "invalid",
            "date_of_birth": "invalid",
            "notes": "invalid",
        }
    }
    assert customers_in_db(db) == 0


@pytest.mark.parametrize(
    "date_of_birth", ["17/05/2001", 990057600, "2001-05-17T00:00:00", None]
)
def test_a_date_of_birth_is_only_yyyy_mm_dd(
    as_manager: Staff, date_of_birth: object
) -> None:
    answer = as_manager.send(
        "POST", "/api/customers", {**NOA, "date_of_birth": date_of_birth}
    )
    assert answer.status_code == 422


def test_an_active_customers_phone_is_a_conflict(
    db: Session, as_manager: Staff, noa_id: int
) -> None:
    answer = as_manager.send(
        "POST", "/api/customers", {**NOA, "first_name": "דנה", "phone": "+972501234567"}
    )

    assert answer.status_code == 409
    assert answer.json() == {"error": "phone_taken", "customer_id": noa_id}
    assert customers_in_db(db) == 1


def test_an_inactive_customers_phone_brings_them_back(
    db: Session, as_manager: Staff, noa_id: int
) -> None:
    as_manager.send("POST", f"/api/customers/{noa_id}/deactivate")

    answer = as_manager.send("POST", "/api/customers", {**NOA, "first_name": "דנה"})

    assert answer.status_code == 201
    assert answer.json()["reactivated"] is True
    assert answer.json()["customer"]["id"] == noa_id
    assert answer.json()["customer"]["first_name"] == "נועה"
    assert customers_in_db(db) == 1


# ── The list and the page ───────────────────────────────────────────────


def test_the_list_shows_active_or_inactive_customers(
    as_manager: Staff, noa_id: int
) -> None:
    dana = as_manager.send(
        "POST", "/api/customers", {**NOA, "first_name": "דנה", "phone": "0527654321"}
    ).json()["customer"]
    as_manager.send("POST", f"/api/customers/{noa_id}/deactivate")

    active = as_manager.get("/api/customers").json()["customers"]
    inactive = as_manager.get("/api/customers", params={"active": "false"}).json()[
        "customers"
    ]

    assert active == [
        {
            "id": dana["id"],
            "first_name": "דנה",
            "last_name": "לוי",
            "phone": "+972527654321",
            "active": True,
        }
    ]
    assert [c["id"] for c in inactive] == [noa_id]


@pytest.mark.parametrize(
    "path", ["/api/customers/999", "/api/customers/999/reactivate"]
)
def test_an_unknown_customer_is_a_404(as_manager: Staff, path: str) -> None:
    method = "GET" if path.endswith("999") else "POST"
    assert as_manager.send(method, path).status_code == 404


@pytest.mark.parametrize("customer_id", ["0", "-1", "abc", str(2**63)])
def test_a_malformed_id_is_a_422(as_manager: Staff, customer_id: str) -> None:
    assert as_manager.get(f"/api/customers/{customer_id}").status_code == 422


# ── Editing ─────────────────────────────────────────────────────────────


def test_editing_changes_only_the_fields_sent(as_manager: Staff, noa_id: int) -> None:
    answer = as_manager.send(
        "PATCH",
        f"/api/customers/{noa_id}",
        {"last_name": "כהן", "phone": "052 765 4321"},
    )

    assert answer.status_code == 200
    body = answer.json()
    assert (body["first_name"], body["last_name"]) == ("נועה", "כהן")
    assert body["phone"] == "+972527654321"


def test_a_bad_edit_names_the_field(as_manager: Staff, noa_id: int) -> None:
    answer = as_manager.send("PATCH", f"/api/customers/{noa_id}", {"phone": "nope"})
    assert answer.status_code == 400
    assert answer.json() == {"errors": {"phone": "invalid"}}


def test_editing_to_another_customers_phone_is_a_conflict(
    as_manager: Staff, noa_id: int
) -> None:
    dana = as_manager.send(
        "POST", "/api/customers", {**NOA, "first_name": "דנה", "phone": "0527654321"}
    ).json()["customer"]

    answer = as_manager.send(
        "PATCH", f"/api/customers/{noa_id}", {"phone": "0527654321"}
    )

    assert answer.status_code == 409
    assert answer.json() == {"error": "phone_taken", "customer_id": dana["id"]}


def test_an_inactive_customer_cant_be_edited(as_manager: Staff, noa_id: int) -> None:
    as_manager.send("POST", f"/api/customers/{noa_id}/deactivate")

    edit = as_manager.send("PATCH", f"/api/customers/{noa_id}", {"notes": "x"})
    birth = as_manager.send(
        "PUT", f"/api/customers/{noa_id}/date-of-birth", {"date_of_birth": "2010-01-01"}
    )

    for answer in (edit, birth):
        assert answer.status_code == 409
        assert answer.json() == {"error": "customer_inactive", "customer_id": None}


# ── The manager's actions ───────────────────────────────────────────────


def test_the_manager_changes_the_date_of_birth(
    db: Session, as_manager: Staff, noa_id: int
) -> None:
    answer = as_manager.send(
        "PUT", f"/api/customers/{noa_id}/date-of-birth", {"date_of_birth": "2010-03-04"}
    )

    assert answer.status_code == 200
    assert answer.json()["date_of_birth"] == "2010-03-04"
    assert log_actions(db) == ["customer.create", "customer.change_date_of_birth"]


def test_the_manager_deactivates_and_reactivates(
    db: Session, as_manager: Staff, noa_id: int
) -> None:
    off = as_manager.send("POST", f"/api/customers/{noa_id}/deactivate")
    on = as_manager.send("POST", f"/api/customers/{noa_id}/reactivate")

    assert off.json()["active"] is False
    assert on.json()["active"] is True
    assert log_actions(db) == [
        "customer.create",
        "customer.deactivate",
        "customer.reactivate",
    ]


def test_customer_answers_are_not_cached(as_manager: Staff, noa_id: int) -> None:
    answer = as_manager.get(f"/api/customers/{noa_id}")
    assert answer.headers["Cache-Control"] == "no-store"
