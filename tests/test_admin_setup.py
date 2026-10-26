"""First-run setup on the admin app: the first manager and the gym's name,
saved together or not at all, and the page gone once it's done. Names and
PINs are made up."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.admin.security import SESSION_COOKIE
from app.core import pins
from app.core.db import get_engine
from app.core.gym_settings import load_gym_settings
from app.core.models import ActivityLogEntry, StaffSession, StaffUser
from app.core.permissions import Role
from app.core.staff_sessions import find_session

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
GOOD_FORM = {
    "gym_name": "מכון הדוגמה",
    "display_name": "נועה",
    "pin": PIN,
    "pin_again": PIN,
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
    with Session(get_engine()) as session:
        yield session


def submit(client: TestClient, **changes: str):
    return client.post("/setup", data={**GOOD_FORM, **changes}, headers=SAME_ORIGIN)


def assert_nothing_saved(db: Session) -> None:
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(StaffUser)) == 0
    assert load_gym_settings(db).gym_name is None
    assert db.scalar(select(func.count()).select_from(ActivityLogEntry)) == 0


# ── Before setup ────────────────────────────────────────────────────────


def test_the_setup_page_asks_in_hebrew(client: TestClient) -> None:
    response = client.get("/setup")

    assert response.status_code == 200
    assert '<html lang="he" dir="rtl">' in response.text
    assert "הגדרה ראשונה" in response.text
    for field in ("gym_name", "display_name", "pin", "pin_again"):
        assert f'name="{field}"' in response.text


# ── Finishing ───────────────────────────────────────────────────────────


def test_setup_saves_the_manager_and_gym_name_and_logs_in(
    client: TestClient, db: Session
) -> None:
    response = submit(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    manager = db.scalars(select(StaffUser)).one()
    assert manager.display_name == "נועה"
    assert manager.role is Role.MANAGER
    assert manager.active
    assert pins.pin_matches(manager.pin_hash, PIN)
    assert load_gym_settings(db).gym_name == "מכון הדוגמה"

    token = response.cookies[SESSION_COOKIE]
    session = find_session(db, token)
    assert session is not None
    assert session.staff_user_id == manager.id


def test_setup_logs_the_manager_as_making_both_changes(
    client: TestClient, db: Session
) -> None:
    submit(client)

    manager = db.scalars(select(StaffUser)).one()
    entries = db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id))
    assert [
        (
            entry.staff_user_id,
            entry.action,
            entry.before_json and json.loads(entry.before_json),
            json.loads(entry.after_json),
        )
        for entry in entries
    ] == [
        (
            manager.id,
            "staff.create",
            None,
            {"display_name": "נועה", "role": "manager", "active": True},
        ),
        (
            manager.id,
            "settings.update",
            {"gym_name": None},
            {"gym_name": "מכון הדוגמה"},
        ),
    ]


def test_the_session_cookie_is_locked_down(client: TestClient) -> None:
    cookie = submit(client).headers["set-cookie"].lower()

    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    # Gone when the browser closes.
    assert "max-age" not in cookie
    assert "expires" not in cookie


def test_after_setup_the_page_is_gone(client: TestClient, db: Session) -> None:
    submit(client)

    assert client.get("/setup").status_code == 404
    second = submit(client, display_name="דנה")
    assert second.status_code == 404
    assert db.scalar(select(func.count()).select_from(StaffUser)) == 1


def test_a_deactivated_manager_still_counts_as_setup_done(
    client: TestClient, db: Session
) -> None:
    submit(client)
    db.scalars(select(StaffUser)).one().active = False
    db.commit()

    assert client.get("/setup").status_code == 404


# ── Bad values ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"pin": "123456", "pin_again": "123456"}, "pin"),
        ({"pin": "12345", "pin_again": "12345"}, "pin"),
        ({"pin": "", "pin_again": ""}, "pin"),
        ({"pin_again": "570461"}, "pin_again"),
        ({"gym_name": "   "}, "gym_name"),
        ({"gym_name": "x" * 101}, "gym_name"),
        ({"display_name": ""}, "display_name"),
        ({"display_name": "נועה​"}, "display_name"),
    ],
    ids=[
        "straight-run",
        "short-pin",
        "no-pin",
        "pins-differ",
        "blank-gym",
        "long-gym",
        "no-name",
        "invisible-char",
    ],
)
def test_a_bad_value_saves_nothing_and_says_where(
    client: TestClient, db: Session, changes: dict[str, str], field: str
) -> None:
    response = submit(client, **changes)

    assert response.status_code == 422
    assert 'role="alert"' in response.text
    assert SESSION_COOKIE not in response.cookies
    assert_nothing_saved(db)
    assert db.scalar(select(func.count()).select_from(StaffSession)) == 0


def test_every_problem_is_shown_at_once(client: TestClient, db: Session) -> None:
    response = submit(client, gym_name="", display_name="", pin="1", pin_again="1")

    assert response.text.count('role="alert"') == 3
    assert_nothing_saved(db)


def test_the_form_keeps_the_names_but_never_the_pins(client: TestClient) -> None:
    response = submit(client, pin="570461", pin_again="570462")

    assert 'value="מכון הדוגמה"' in response.text
    assert 'value="נועה"' in response.text
    assert "57046" not in response.text


def test_typed_values_are_escaped_when_shown_again(client: TestClient) -> None:
    response = submit(client, gym_name='<b onclick="x">', pin_again="570461")

    assert '<b onclick="x">' not in response.text
    assert "&lt;b onclick=&#34;x&#34;&gt;" in response.text


def test_a_cross_site_setup_is_refused(client: TestClient, db: Session) -> None:
    response = client.post(
        "/setup", data=GOOD_FORM, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert_nothing_saved(db)


def test_a_rebinding_site_cant_reach_setup(migrated_db: Path) -> None:
    with TestClient(app, base_url="http://evil.example") as client:
        response = client.post(
            "/setup", data=GOOD_FORM, headers={"Origin": "http://evil.example"}
        )

    assert response.status_code == 400
