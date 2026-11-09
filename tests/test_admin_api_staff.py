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
    create_owner,
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
def owner(db: Session) -> StaffUser:
    member = create_owner(db, "מנהלת", PIN)
    db.commit()
    return member


@pytest.fixture
def instructor(db: Session, owner: StaffUser) -> StaffUser:
    member = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=owner)
    db.commit()
    return member


# The browsers log_in() opened in this test, closed after it.
_browsers: list[TestClient] = []


@pytest.fixture(autouse=True)
def close_browsers() -> Iterator[None]:
    yield
    while _browsers:
        _browsers.pop().close()


def log_in(member: StaffUser) -> TestClient:
    """A browser of its own, logged in as ``member``, sending its CSRF
    token with every request."""
    browser = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    _browsers.append(browser)
    answer = browser.post(
        "/api/login", json={"staff_id": member.id, "pin": PIN}, headers=SAME_ORIGIN
    )
    assert answer.status_code == 200
    browser.headers.update({**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]})
    return browser


@pytest.fixture
def as_owner(owner: StaffUser) -> TestClient:
    return log_in(owner)


def reloaded(db: Session, member: StaffUser) -> StaffUser:
    db.expire_all()
    return db.get_one(StaffUser, member.id)


def staff_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StaffUser)) or 0


# ── Adding ──────────────────────────────────────────────────────────────


def test_adding_a_member(as_owner: TestClient, db: Session) -> None:
    answer = as_owner.post(
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
        "can_reset_pin": True,
        "can_change_role": True,
        "can_toggle_active": True,
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
    as_owner: TestClient, db: Session, body: dict[str, str], field: str
) -> None:
    before = staff_count(db)

    answer = as_owner.post("/api/staff", json={**body, "role": "instructor"})

    assert answer.status_code == 400
    assert answer.json() == {"errors": {field: "invalid"}}
    assert staff_count(db) == before


def test_a_taken_name_is_a_conflict(
    as_owner: TestClient, instructor: StaffUser
) -> None:
    answer = as_owner.post(
        "/api/staff", json={"display_name": "מדריך", "role": "manager", "pin": PIN}
    )

    assert answer.status_code == 409
    assert answer.json() == {"error": "name_taken"}


# ── PIN reset ───────────────────────────────────────────────────────────


def test_a_pin_reset_lifts_the_lockout_and_logs_them_out(
    as_owner: TestClient, db: Session, instructor: StaffUser
) -> None:
    instructors_browser = log_in(instructor)
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, NEW_PIN)
    db.commit()
    listed = as_owner.get("/api/staff").json()["staff"]
    assert next(m for m in listed if m["id"] == instructor.id)["locked_until"]

    answer = as_owner.put(f"/api/staff/{instructor.id}/pin", json={"pin": NEW_PIN})

    assert answer.status_code == 200
    assert answer.json()["locked_until"] is None
    assert instructors_browser.get("/api/session").status_code == 401
    assert check_pin(db, reloaded(db, instructor), NEW_PIN) is PinCheck.OK


def test_resetting_your_own_pin_keeps_you_logged_in(
    as_owner: TestClient, owner: StaffUser
) -> None:
    answer = as_owner.put(f"/api/staff/{owner.id}/pin", json={"pin": NEW_PIN})

    assert answer.status_code == 200
    assert as_owner.get("/api/session").status_code == 200


def test_a_bad_new_pin_is_refused(
    as_owner: TestClient, db: Session, instructor: StaffUser
) -> None:
    answer = as_owner.put(f"/api/staff/{instructor.id}/pin", json={"pin": "000000"})

    assert answer.status_code == 400
    assert answer.json() == {"errors": {"pin": "invalid"}}
    assert check_pin(db, reloaded(db, instructor), PIN) is PinCheck.OK


# ── Roles ───────────────────────────────────────────────────────────────


def test_promoting_an_instructor(as_owner: TestClient, instructor: StaffUser) -> None:
    answer = as_owner.put(f"/api/staff/{instructor.id}/role", json={"role": "manager"})

    assert answer.status_code == 200
    assert answer.json()["role"] == "manager"


@pytest.fixture
def manager(db: Session, owner: StaffUser) -> StaffUser:
    member = create_staff_user(db, "יעל", Role.MANAGER, PIN, by=owner)
    db.commit()
    return member


@pytest.mark.parametrize(
    ("method", "action", "body"),
    [
        ("PUT", "role", {"role": "manager"}),
        ("POST", "deactivate", None),
    ],
)
@pytest.mark.parametrize("by_owner", [True, False], ids=["by_owner", "by_manager"])
def test_nobody_demotes_or_deactivates_the_owner(
    db: Session,
    owner: StaffUser,
    manager: StaffUser,
    by_owner: bool,
    method: str,
    action: str,
    body: dict[str, str] | None,
) -> None:
    browser = log_in(owner if by_owner else manager)

    answer = browser.request(method, f"/api/staff/{owner.id}/{action}", json=body)

    assert answer.status_code == 409
    assert answer.json() == {"error": "owner"}
    member = reloaded(db, owner)
    assert (member.role, member.active) == (Role.OWNER, True)


def test_only_the_owner_resets_the_owners_pin(
    as_owner: TestClient, owner: StaffUser, manager: StaffUser
) -> None:
    answer = log_in(manager).put(f"/api/staff/{owner.id}/pin", json={"pin": NEW_PIN})

    assert answer.status_code == 409
    assert answer.json() == {"error": "owner"}
    assert as_owner.put(f"/api/staff/{owner.id}/pin", json={"pin": NEW_PIN}).is_success


def test_nobody_is_made_the_owner(as_owner: TestClient, instructor: StaffUser) -> None:
    role = as_owner.put(f"/api/staff/{instructor.id}/role", json={"role": "owner"})
    added = as_owner.post(
        "/api/staff", json={"display_name": "גיל", "role": "owner", "pin": PIN}
    )

    assert (role.status_code, added.status_code) == (422, 422)


@pytest.mark.parametrize(
    ("method", "action", "body"),
    [
        ("PUT", "role", {"role": "instructor"}),
        ("PUT", "pin", {"pin": NEW_PIN}),
        ("POST", "deactivate", None),
    ],
)
def test_a_manager_cannot_change_a_managers_account(
    db: Session,
    owner: StaffUser,
    manager: StaffUser,
    method: str,
    action: str,
    body: dict[str, str] | None,
) -> None:
    other = create_staff_user(db, "גיל", Role.MANAGER, PIN, by=owner)
    db.commit()
    browser = log_in(manager)

    answer = browser.request(method, f"/api/staff/{other.id}/{action}", json=body)

    assert answer.status_code == 403
    member = reloaded(db, other)
    assert (member.role, member.active) == (Role.MANAGER, True)
    assert check_pin(db, member, PIN) is PinCheck.OK


def test_a_manager_cannot_add_or_promote_managers(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    browser = log_in(manager)
    before = staff_count(db)

    added = browser.post(
        "/api/staff", json={"display_name": "גיל", "role": "manager", "pin": NEW_PIN}
    )
    promoted = browser.put(f"/api/staff/{instructor.id}/role", json={"role": "manager"})

    assert (added.status_code, promoted.status_code) == (403, 403)
    assert staff_count(db) == before
    assert reloaded(db, instructor).role is Role.INSTRUCTOR


def test_a_manager_manages_instructors(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    browser = log_in(manager)

    added = browser.post(
        "/api/staff", json={"display_name": "גיל", "role": "instructor", "pin": PIN}
    )
    reset = browser.put(f"/api/staff/{instructor.id}/pin", json={"pin": NEW_PIN})
    deactivated = browser.post(f"/api/staff/{instructor.id}/deactivate")

    assert [added.status_code, reset.status_code, deactivated.status_code] == [
        201,
        200,
        200,
    ]


def test_the_list_says_what_the_viewer_may_do(
    owner: StaffUser, manager: StaffUser, instructor: StaffUser
) -> None:
    listed = log_in(manager).get("/api/staff").json()["staff"]

    offered = {
        m["id"]: (m["can_reset_pin"], m["can_change_role"], m["can_toggle_active"])
        for m in listed
    }
    assert offered == {
        owner.id: (False, False, False),
        manager.id: (True, False, False),
        instructor.id: (True, False, True),
    }


def test_the_owner_deactivates_a_manager(
    as_owner: TestClient, manager: StaffUser
) -> None:
    managers_browser = log_in(manager)

    answer = as_owner.post(f"/api/staff/{manager.id}/deactivate")

    assert answer.status_code == 200
    assert managers_browser.get("/api/session").status_code == 401


# ── Deactivating and reactivating ───────────────────────────────────────


def test_deactivating_logs_them_out_and_reactivating_brings_them_back(
    as_owner: TestClient, instructor: StaffUser
) -> None:
    instructors_browser = log_in(instructor)

    answer = as_owner.post(f"/api/staff/{instructor.id}/deactivate")

    assert answer.status_code == 200
    assert answer.json()["active"] is False
    assert instructors_browser.get("/api/session").status_code == 401

    answer = as_owner.post(f"/api/staff/{instructor.id}/reactivate")

    assert answer.status_code == 200
    assert answer.json()["active"] is True


def test_reactivating_into_a_taken_name_is_a_conflict(
    as_owner: TestClient, db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    as_owner.post(f"/api/staff/{instructor.id}/deactivate")
    create_staff_user(db, "מדריך", Role.INSTRUCTOR, NEW_PIN, by=owner)
    db.commit()

    answer = as_owner.post(f"/api/staff/{instructor.id}/reactivate")

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
    as_owner: TestClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    assert as_owner.request(method, path, json=body).status_code == 404


def test_every_change_is_logged_as_the_owner(
    as_owner: TestClient, db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    as_owner.put(f"/api/staff/{instructor.id}/pin", json={"pin": NEW_PIN})
    as_owner.put(f"/api/staff/{instructor.id}/role", json={"role": "manager"})
    as_owner.post(f"/api/staff/{instructor.id}/deactivate")

    entries = db.scalars(
        select(ActivityLogEntry)
        .where(ActivityLogEntry.target_id == instructor.id)
        .order_by(ActivityLogEntry.id)
    ).all()
    assert [(e.staff_user_id, e.action) for e in entries][-3:] == [
        (owner.id, "staff.reset_pin"),
        (owner.id, "staff.change_role"),
        (owner.id, "staff.deactivate"),
    ]
