"""The lock screen, logging in, the session and locking through the admin
JSON API, on the real admin app. Names and PINs are made up."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.csrf import csrf_token
from app.admin.main import app
from app.admin.security import SESSION_COOKIE
from app.core import pins
from app.core.db import get_engine
from app.core.models import Setting, StaffSession, StaffUser
from app.core.permissions import Role
from app.core.staff import (
    MAX_FAILED_ATTEMPTS,
    create_first_manager,
    create_staff_user,
    deactivate,
)

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
WRONG_PIN = "570461"


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
def noa(db: Session) -> StaffUser:
    staff = create_first_manager(db, "נועה", PIN)
    db.commit()
    return staff


@pytest.fixture
def dana(db: Session, noa: StaffUser) -> StaffUser:
    staff = create_staff_user(db, "דנה", Role.INSTRUCTOR, PIN, by=noa)
    db.commit()
    return staff


def log_in(client: TestClient, staff_id: object, pin: str = PIN):
    return client.post(
        "/api/login", json={"staff_id": staff_id, "pin": pin}, headers=SAME_ORIGIN
    )


def lock(client: TestClient, token: str | None):
    headers = {**SAME_ORIGIN, "X-CSRF-Token": csrf_token(token)} if token else {}
    return client.post("/api/lock", headers=headers or SAME_ORIGIN)


def reload(db: Session, staff: StaffUser) -> StaffUser:
    db.expire_all()
    return db.get(StaffUser, staff.id)


# ── The lock screen ─────────────────────────────────────────────────────


def test_before_setup_the_lock_screen_says_setup_is_needed(
    client: TestClient,
) -> None:
    response = client.get("/api/lock-screen")

    assert response.status_code == 200
    assert response.json() == {"setup_needed": True, "staff": []}


def test_the_lock_screen_lists_only_active_staff_by_name(
    client: TestClient, db: Session, noa: StaffUser, dana: StaffUser
) -> None:
    tal = create_staff_user(db, "טל", Role.INSTRUCTOR, PIN, by=noa)
    deactivate(db, tal, by=noa)
    db.commit()

    response = client.get("/api/lock-screen")

    assert response.status_code == 200
    # Ids and names only: nothing about roles, PINs or lockouts.
    assert response.json() == {
        "setup_needed": False,
        "staff": [
            {"id": dana.id, "display_name": "דנה"},
            {"id": noa.id, "display_name": "נועה"},
        ],
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_showing_the_lock_screen_ends_the_session(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    token = log_in(client, noa.id).cookies[SESSION_COOKIE]

    # Lock, Back, a typed address, or another tab's auto-lock timer.
    response = client.get("/api/lock-screen")

    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert db.scalars(select(StaffSession)).one().ended_at is not None
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/session").status_code == 401


def test_the_lock_screen_without_a_session_sets_no_cookie(
    client: TestClient, noa: StaffUser
) -> None:
    response = client.get("/api/lock-screen")

    assert "set-cookie" not in response.headers


# ── Logging in ──────────────────────────────────────────────────────────


def test_the_right_pin_logs_in_and_returns_the_session(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = log_in(client, noa.id)

    assert response.status_code == 200
    token = response.cookies[SESSION_COOKIE]
    assert response.json() == {
        "staff": {"id": noa.id, "display_name": "נועה", "role": "manager"},
        "csrf_token": csrf_token(token),
        "lock_after_seconds": 300,
    }
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    # The session token itself is only ever in the HttpOnly cookie.
    assert token not in response.text


def test_an_instructor_gets_the_instructor_lock_time(
    client: TestClient, dana: StaffUser
) -> None:
    response = log_in(client, dana.id)

    assert response.json()["staff"]["role"] == "instructor"
    assert response.json()["lock_after_seconds"] == 3600


def test_a_wrong_pin_is_refused_and_counted(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = log_in(client, noa.id, WRONG_PIN)

    assert response.status_code == 401
    assert response.json() == {"error": "wrong_pin", "locked_until": None}
    assert SESSION_COOKIE not in response.cookies
    # The refused login was committed, not rolled back (decision 0018).
    assert reload(db, noa).failed_attempts == 1


def test_too_many_wrong_pins_lock_the_account(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        response = log_in(client, noa.id, WRONG_PIN)

    assert response.status_code == 401
    assert response.json()["error"] == "locked"
    locked_until = datetime.fromisoformat(response.json()["locked_until"])
    # In the gym's time zone, with its offset, and the same moment as stored.
    assert locked_until.utcoffset() is not None
    assert locked_until == reload(db, noa).locked_until

    # Even the right PIN is refused while locked.
    locked = log_in(client, noa.id)
    assert locked.json()["error"] == "locked"
    assert SESSION_COOKIE not in locked.cookies
    assert db.scalars(select(StaffSession)).all() == []


def test_a_deactivated_staff_member_cant_log_in(
    client: TestClient, db: Session, noa: StaffUser, dana: StaffUser
) -> None:
    deactivate(db, dana, by=noa)
    db.commit()

    response = log_in(client, dana.id)

    assert response.status_code == 401
    assert response.json()["error"] == "no_such_staff"


@pytest.mark.usefixtures("noa")
def test_an_unknown_staff_id_is_refused(client: TestClient) -> None:
    response = log_in(client, 999)

    assert response.status_code == 401
    assert response.json()["error"] == "no_such_staff"


@pytest.mark.usefixtures("noa")
@pytest.mark.parametrize("staff_id", ["abc", 0, -1, 2**63, 10**30, None], ids=str)
def test_a_malformed_staff_id_is_a_bad_request(
    client: TestClient, staff_id: object
) -> None:
    # Including ids beyond SQLite's range, which used to crash the lookup.
    response = log_in(client, staff_id)

    assert response.status_code == 422


def test_a_huge_pin_is_refused_before_the_pin_check(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = log_in(client, noa.id, "1" * 101)

    assert response.status_code == 422
    assert reload(db, noa).failed_attempts == 0


def test_a_cross_site_login_is_refused(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = client.post(
        "/api/login",
        json={"staff_id": noa.id, "pin": PIN},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert db.scalars(select(StaffSession)).all() == []


def test_a_new_login_ends_the_browsers_previous_session(
    client: TestClient, db: Session, noa: StaffUser, dana: StaffUser
) -> None:
    log_in(client, noa.id)
    log_in(client, dana.id)

    sessions = db.scalars(select(StaffSession).order_by(StaffSession.id)).all()
    assert [s.staff_user_id for s in sessions] == [noa.id, dana.id]
    assert sessions[0].ended_at is not None
    assert sessions[1].ended_at is None
    assert client.get("/api/session").json()["staff"]["display_name"] == "דנה"


# ── The session ─────────────────────────────────────────────────────────


def test_the_session_says_who_is_logged_in(client: TestClient, noa: StaffUser) -> None:
    token = log_in(client, noa.id).cookies[SESSION_COOKIE]

    response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json()["staff"]["display_name"] == "נועה"
    assert response.json()["csrf_token"] == csrf_token(token)
    assert response.headers["Cache-Control"] == "no-store"


def test_no_session_is_a_401_saying_where_to_go(
    client: TestClient, noa: StaffUser
) -> None:
    response = client.get("/api/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "not_logged_in", "setup_needed": False}
    assert response.headers["Cache-Control"] == "no-store"


def test_before_setup_the_401_says_setup_is_needed(client: TestClient) -> None:
    response = client.get("/api/session")

    assert response.json() == {"detail": "not_logged_in", "setup_needed": True}


def test_a_broken_settings_row_doesnt_lock_staff_out(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    db.add(Setting(key="gym_nmae", value='"typo"', updated_at=noa.created_at))
    db.commit()

    log_in(client, noa.id)

    assert client.get("/api/session").status_code == 200


# ── Locking ─────────────────────────────────────────────────────────────


def test_lock_ends_the_session(client: TestClient, db: Session, noa: StaffUser) -> None:
    token = log_in(client, noa.id).cookies[SESSION_COOKIE]

    response = lock(client, token)

    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert db.scalars(select(StaffSession)).one().ended_at is not None
    # The old token is useless now, even if the browser kept it.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/session").status_code == 401


def test_lock_without_the_csrf_token_is_refused(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    log_in(client, noa.id)

    response = lock(client, None)

    assert response.status_code == 403
    assert db.scalars(select(StaffSession)).one().ended_at is None
    assert client.get("/api/session").status_code == 200


def test_lock_without_a_session_is_a_401(client: TestClient, noa: StaffUser) -> None:
    response = lock(client, None)

    assert response.status_code == 401
