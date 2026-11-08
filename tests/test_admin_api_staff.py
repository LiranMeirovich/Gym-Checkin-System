"""The staff account routes of the admin JSON API, on the real admin app:
adding, PIN resets, roles, deactivating, and their refusals. Who may use
them is tested in ``test_admin_manager_only_routes.py``. Names and PINs
are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins, staff
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, StaffUser
from app.core.permissions import Role
from app.core.staff import (
    PinCheck,
    check_pin,
    create_first_manager,
    create_staff_user,
)

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
NEW_PIN = "570461"


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
    member = create_first_manager(db, "מנהלת", PIN)
    db.commit()
    return member


@pytest.fixture
def instructor(db: Session, manager: StaffUser) -> StaffUser:
    member = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()
    return member


def log_in(member: StaffUser) -> TestClient:
    """A browser of its own, logged in as ``member``, sending its CSRF
    token with every request."""
    browser = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    answer = browser.post(
        "/api/login", json={"staff_id": member.id, "pin": PIN}, headers=SAME_ORIGIN
    )
    assert answer.status_code == 200
    browser.headers.update({**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]})
    return browser


@pytest.fixture
def as_manager(manager: StaffUser) -> TestClient:
    return log_in(manager)


def reloaded(db: Session, member: StaffUser) -> StaffUser:
    db.expire_all()
    return db.get_one(StaffUser, member.id)


def staff_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StaffUser)) or 0


# ── Adding ──────────────────────────────────────────────────────────────


def test_adding_a_member(as_manager: TestClient, db: Session) -> None:
    answer = as_manager.post(
        "/api/staff", json={"display_name": " יעל ", "role": "instructor", "pin": PIN}
    )

    assert answer.status_code == 201
    added = answer.json()
    assert added == {
        "id": added["id"],
        "display_name": "יעל",
        "role": "instructor",
        "active": True,
        "locked_until": None,
    }
    assert check_pin(db, db.get_one(StaffUser, added["id"]), PIN) is PinCheck.OK


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"display_name": "", "pin": PIN}, "display_name"),
        ({"display_name": "יעל", "pin": "123456"}, "pin"),
        ({"display_name": "יעל", "pin": "12"}, "pin"),
    ],
)
def test_a_broken_field_is_named(
    as_manager: TestClient, db: Session, body: dict[str, str], field: str
) -> None:
    before = staff_count(db)

    answer = as_manager.post("/api/staff", json={**body, "role": "instructor"})

    assert answer.status_code == 400
    assert answer.json() == {"errors": {field: "invalid"}}
    assert staff_count(db) == before


def test_a_taken_name_is_a_conflict(
    as_manager: TestClient, instructor: StaffUser
) -> None:
    answer = as_manager.post(
        "/api/staff", json={"display_name": "מדריך", "role": "manager", "pin": PIN}
    )

    assert answer.status_code == 409
    assert answer.json() == {"error": "name_taken"}


# ── PIN reset ───────────────────────────────────────────────────────────


def test_a_pin_reset_lifts_the_lockout_and_logs_them_out(
    as_manager: TestClient, db: Session, instructor: StaffUser
) -> None:
    instructors_browser = log_in(instructor)
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, NEW_PIN)
    db.commit()
    listed = as_manager.get("/api/staff").json()["staff"]
    assert next(m for m in listed if m["id"] == instructor.id)["locked_until"]

    answer = as_manager.put(f"/api/staff/{instructor.id}/pin", json={"pin": NEW_PIN})

    assert answer.status_code == 200
    assert answer.json()["locked_until"] is None
    assert instructors_browser.get("/api/session").status_code == 401
    assert check_pin(db, reloaded(db, instructor), NEW_PIN) is PinCheck.OK


def test_resetting_your_own_pin_keeps_you_logged_in(
    as_manager: TestClient, manager: StaffUser
) -> None:
    answer = as_manager.put(f"/api/staff/{manager.id}/pin", json={"pin": NEW_PIN})

    assert answer.status_code == 200
    assert as_manager.get("/api/session").status_code == 200


def test_a_bad_new_pin_is_refused(
    as_manager: TestClient, db: Session, instructor: StaffUser
) -> None:
    answer = as_manager.put(f"/api/staff/{instructor.id}/pin", json={"pin": "000000"})

    assert answer.status_code == 400
    assert answer.json() == {"errors": {"pin": "invalid"}}
    assert check_pin(db, reloaded(db, instructor), PIN) is PinCheck.OK


# ── Roles ───────────────────────────────────────────────────────────────


def test_promoting_an_instructor(as_manager: TestClient, instructor: StaffUser) -> None:
    answer = as_manager.put(
        f"/api/staff/{instructor.id}/role", json={"role": "manager"}
    )

    assert answer.status_code == 200
    assert answer.json()["role"] == "manager"


def test_the_only_manager_cannot_demote_themselves(
    as_manager: TestClient, manager: StaffUser
) -> None:
    answer = as_manager.put(
        f"/api/staff/{manager.id}/role", json={"role": "instructor"}
    )

    assert answer.status_code == 409
    assert answer.json() == {"error": "last_manager"}


@pytest.mark.parametrize(
    ("method", "action", "body"),
    [("PUT", "role", {"role": "instructor"}), ("POST", "deactivate", None)],
)
def test_a_manager_cannot_demote_or_deactivate_themselves(
    as_manager: TestClient,
    db: Session,
    manager: StaffUser,
    method: str,
    action: str,
    body: dict[str, str] | None,
) -> None:
    create_staff_user(db, "יעל", Role.MANAGER, PIN, by=manager)
    db.commit()

    answer = as_manager.request(method, f"/api/staff/{manager.id}/{action}", json=body)

    assert answer.status_code == 409
    assert answer.json() == {"error": "own_account"}
    member = reloaded(db, manager)
    assert (member.role, member.active) == (Role.MANAGER, True)


# ── Deactivating and reactivating ───────────────────────────────────────


def test_deactivating_logs_them_out_and_reactivating_brings_them_back(
    as_manager: TestClient, instructor: StaffUser
) -> None:
    instructors_browser = log_in(instructor)

    answer = as_manager.post(f"/api/staff/{instructor.id}/deactivate")

    assert answer.status_code == 200
    assert answer.json()["active"] is False
    assert instructors_browser.get("/api/session").status_code == 401

    answer = as_manager.post(f"/api/staff/{instructor.id}/reactivate")

    assert answer.status_code == 200
    assert answer.json()["active"] is True


def test_reactivating_into_a_taken_name_is_a_conflict(
    as_manager: TestClient, db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    as_manager.post(f"/api/staff/{instructor.id}/deactivate")
    create_staff_user(db, "מדריך", Role.INSTRUCTOR, NEW_PIN, by=manager)
    db.commit()

    answer = as_manager.post(f"/api/staff/{instructor.id}/reactivate")

    assert answer.status_code == 409
    assert answer.json() == {"error": "name_taken"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", "/api/staff/999/pin", {"pin": NEW_PIN}),
        ("PUT", "/api/staff/999/role", {"role": "manager"}),
        ("POST", "/api/staff/999/deactivate", None),
        ("POST", "/api/staff/999/reactivate", None),
    ],
)
def test_an_unknown_member_is_not_found(
    as_manager: TestClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    assert as_manager.request(method, path, json=body).status_code == 404


def test_every_change_is_logged_as_the_manager(
    as_manager: TestClient, db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    as_manager.put(f"/api/staff/{instructor.id}/pin", json={"pin": NEW_PIN})
    as_manager.put(f"/api/staff/{instructor.id}/role", json={"role": "manager"})
    as_manager.post(f"/api/staff/{instructor.id}/deactivate")

    entries = db.scalars(
        select(ActivityLogEntry)
        .where(ActivityLogEntry.target_id == instructor.id)
        .order_by(ActivityLogEntry.id)
    ).all()
    assert [(e.staff_user_id, e.action) for e in entries][-3:] == [
        (manager.id, "staff.reset_pin"),
        (manager.id, "staff.change_role"),
        (manager.id, "staff.deactivate"),
    ]
