"""The lock screen, logging in and locking on the real admin app. Names and
PINs are made up."""

from collections.abc import Iterator
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
from app.core.models import StaffSession, StaffUser
from app.core.permissions import Role
from app.core.staff import MAX_FAILED_ATTEMPTS, create_staff_user, deactivate

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
    staff = create_staff_user(db, "נועה", Role.MANAGER, PIN)
    db.commit()
    return staff


@pytest.fixture
def dana(db: Session) -> StaffUser:
    staff = create_staff_user(db, "דנה", Role.INSTRUCTOR, PIN)
    db.commit()
    return staff


def log_in(client: TestClient, staff: StaffUser, pin: str = PIN):
    return client.post(
        "/login", data={"staff_id": str(staff.id), "pin": pin}, headers=SAME_ORIGIN
    )


def reload(db: Session, staff: StaffUser) -> StaffUser:
    db.expire_all()
    return db.get(StaffUser, staff.id)


# ── The lock screen ─────────────────────────────────────────────────────


def test_before_setup_the_lock_screen_sends_to_setup(client: TestClient) -> None:
    response = client.get("/login")

    assert response.status_code == 303
    assert response.headers["location"] == "/setup"


def test_the_lock_screen_lists_only_active_staff(
    client: TestClient, db: Session, noa: StaffUser, dana: StaffUser
) -> None:
    tal = create_staff_user(db, "טל", Role.INSTRUCTOR, PIN)
    deactivate(db, tal)
    db.commit()

    response = client.get("/login")

    assert response.status_code == 200
    assert "נועה" in response.text
    assert "דנה" in response.text
    assert "טל" not in response.text
    # No PIN box until a name is tapped.
    assert 'name="pin"' not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_tapping_a_name_asks_for_their_pin(client: TestClient, noa: StaffUser) -> None:
    response = client.get(f"/login?staff={noa.id}")

    assert 'name="pin"' in response.text
    assert f'name="staff_id" value="{noa.id}"' in response.text


@pytest.mark.usefixtures("noa")
@pytest.mark.parametrize("staff", ["999", "abc", "-1", "١"])
def test_an_unknown_name_gets_no_pin_box(client: TestClient, staff: str) -> None:
    response = client.get(f"/login?staff={staff}")

    assert response.status_code == 200
    assert 'name="pin"' not in response.text
    assert 'role="alert"' in response.text


# ── Logging in ──────────────────────────────────────────────────────────


def test_the_right_pin_logs_in_and_goes_home(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = log_in(client, noa)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    home = client.get("/")
    assert home.status_code == 200
    assert "נועה" in home.text
    assert "מנהל/ת" in home.text
    assert home.headers["Cache-Control"] == "no-store"


def test_a_wrong_pin_is_refused_and_counted(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = log_in(client, noa, WRONG_PIN)

    assert response.status_code == 401
    assert "קוד שגוי" in response.text
    assert SESSION_COOKIE not in response.cookies
    # The refused login was committed, not rolled back (decision 0018).
    assert reload(db, noa).failed_attempts == 1


def test_too_many_wrong_pins_lock_the_account(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        response = log_in(client, noa, WRONG_PIN)

    assert response.status_code == 401
    assert "יותר מדי ניסיונות" in response.text
    assert reload(db, noa).locked_until is not None

    # Even the right PIN is refused while locked.
    locked = log_in(client, noa)
    assert locked.status_code == 401
    assert SESSION_COOKIE not in locked.cookies
    assert db.scalars(select(StaffSession)).all() == []


def test_a_deactivated_staff_member_cant_log_in(
    client: TestClient, db: Session, noa: StaffUser, dana: StaffUser
) -> None:
    deactivate(db, dana)
    db.commit()

    response = log_in(client, dana)

    assert response.status_code == 401
    assert SESSION_COOKIE not in response.cookies


@pytest.mark.usefixtures("noa")
@pytest.mark.parametrize("staff_id", ["", "999", "abc"])
def test_an_unknown_staff_id_is_refused(client: TestClient, staff_id: str) -> None:
    response = client.post(
        "/login", data={"staff_id": staff_id, "pin": PIN}, headers=SAME_ORIGIN
    )

    assert response.status_code == 401


def test_a_cross_site_login_is_refused(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    response = client.post(
        "/login",
        data={"staff_id": str(noa.id), "pin": PIN},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert db.scalars(select(StaffSession)).all() == []


def test_a_new_login_ends_the_browsers_previous_session(
    client: TestClient, db: Session, noa: StaffUser, dana: StaffUser
) -> None:
    log_in(client, noa)
    log_in(client, dana)

    sessions = db.scalars(select(StaffSession).order_by(StaffSession.id)).all()
    assert [s.staff_user_id for s in sessions] == [noa.id, dana.id]
    assert sessions[0].ended_at is not None
    assert sessions[1].ended_at is None
    assert "דנה" in client.get("/").text


def test_each_login_gets_a_new_token(client: TestClient, noa: StaffUser) -> None:
    first = log_in(client, noa).cookies[SESSION_COOKIE]
    second = log_in(client, noa).cookies[SESSION_COOKIE]

    assert first != second


# ── Logged-in pages ─────────────────────────────────────────────────────


def test_a_staff_page_carries_the_csrf_token_and_lock_timer(
    client: TestClient, noa: StaffUser
) -> None:
    token = log_in(client, noa).cookies[SESSION_COOKIE]

    page = client.get("/").text

    assert f'name="csrf_token" value="{csrf_token(token)}"' in page
    assert f'"X-CSRF-Token": "{csrf_token(token)}"' in page
    # The default lock time, 5 minutes.
    assert "300 * 1000" in page


def test_an_instructors_page_locks_after_the_instructor_time(
    client: TestClient, noa: StaffUser, dana: StaffUser
) -> None:
    log_in(client, dana)

    page = client.get("/").text

    assert "3600 * 1000" in page
    assert "מדריך/ה" in page


def test_the_home_page_needs_a_login(client: TestClient, noa: StaffUser) -> None:
    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# ── Locking ─────────────────────────────────────────────────────────────


def test_lock_ends_the_session(client: TestClient, db: Session, noa: StaffUser) -> None:
    token = log_in(client, noa).cookies[SESSION_COOKIE]

    response = client.post(
        "/lock", data={"csrf_token": csrf_token(token)}, headers=SAME_ORIGIN
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert db.scalars(select(StaffSession)).one().ended_at is not None
    # The old token is useless now, even if the browser kept it.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/").status_code == 303


def test_lock_without_the_csrf_token_is_refused(
    client: TestClient, db: Session, noa: StaffUser
) -> None:
    log_in(client, noa)

    response = client.post("/lock", headers=SAME_ORIGIN)

    assert response.status_code == 403
    assert db.scalars(select(StaffSession)).one().ended_at is None
    assert client.get("/").status_code == 200
