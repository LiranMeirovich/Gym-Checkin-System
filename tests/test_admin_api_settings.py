"""The settings routes of the admin JSON API, on the real admin app:
reading, saving, refusals and repairing a broken stored row. Who may use
them is tested in ``test_admin_manager_only_routes.py``. Names and
addresses are made up."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins
from app.core.activity_log import Action
from app.core.clock import utc_now
from app.core.db import get_engine
from app.core.gym_settings import load_gym_settings, update_gym_settings
from app.core.models import ActivityLogEntry, Setting, StaffUser
from app.core.staff import create_owner

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"

FORM: dict[str, Any] = {
    "gym_name": "מכון הדוגמה",
    "manager_email": "manager@example.com",
    "report_recipients": ["books@example.com", "owner@example.org"],
    "lock_screen_minutes": 10,
    "instructor_lock_screen_minutes": 90,
}


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def owner(db: Session) -> StaffUser:
    member = create_owner(db, "מנהלת", PIN)
    update_gym_settings(db, {"gym_name": "מכון הדוגמה"}, by=member)
    db.commit()
    return member


@pytest.fixture
def browser(owner: StaffUser) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        answer = client.post(
            "/api/login", json={"staff_id": owner.id, "pin": PIN}, headers=SAME_ORIGIN
        )
        assert answer.status_code == 200
        client.headers.update(
            {**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]}
        )
        yield client


def log_entries(db: Session) -> int:
    # A new read transaction, so the count sees what the app committed.
    db.rollback()
    return (
        db.scalar(
            select(func.count())
            .select_from(ActivityLogEntry)
            .where(ActivityLogEntry.action == Action.SETTINGS_UPDATE)
        )
        or 0
    )


def store_raw(db: Session, key: str, value: str) -> None:
    db.merge(Setting(key=key, value=value, updated_at=utc_now()))
    db.commit()


def test_reading_shows_values_and_defaults(browser: TestClient) -> None:
    answer = browser.get("/api/settings")
    assert answer.status_code == 200
    assert answer.json() == {
        "gym_name": "מכון הדוגמה",
        "manager_email": None,
        "report_recipients": [],
        "lock_screen_minutes": 5,
        "instructor_lock_screen_minutes": 60,
        "problems": [],
        "unknown_settings": False,
    }


def test_saving_the_form(browser: TestClient, db: Session) -> None:
    before = log_entries(db)
    answer = browser.put("/api/settings", json=FORM)
    assert answer.status_code == 200
    assert answer.json() == {**FORM, "problems": [], "unknown_settings": False}

    db.rollback()
    saved = load_gym_settings(db)
    assert saved.manager_email == "manager@example.com"
    assert saved.report_recipients == ("books@example.com", "owner@example.org")
    assert saved.instructor_lock_screen_minutes == 90
    # One entry for the save; the gym name didn't change, so it's not in it.
    assert log_entries(db) == before + 1
    entry = db.scalars(
        select(ActivityLogEntry).order_by(ActivityLogEntry.id.desc())
    ).first()
    assert entry is not None
    assert set(json.loads(entry.after_json or "{}")) == set(FORM) - {"gym_name"}


def test_saving_the_same_form_again_writes_no_log_entry(
    browser: TestClient, db: Session
) -> None:
    browser.put("/api/settings", json=FORM)
    before = log_entries(db)
    assert browser.put("/api/settings", json=FORM).status_code == 200
    assert log_entries(db) == before


def test_clearing_the_manager_email(browser: TestClient, db: Session) -> None:
    browser.put("/api/settings", json=FORM)
    answer = browser.put("/api/settings", json={**FORM, "manager_email": None})
    assert answer.status_code == 200
    assert answer.json()["manager_email"] is None
    db.rollback()
    assert db.get(Setting, "manager_email") is None


@pytest.mark.parametrize(
    ("change", "errors", "bad_recipients"),
    [
        ({"gym_name": "   "}, {"gym_name": "invalid"}, []),
        ({"manager_email": "not an address"}, {"manager_email": "invalid"}, []),
        ({"lock_screen_minutes": 0}, {"lock_screen_minutes": "invalid"}, []),
        (
            {"instructor_lock_screen_minutes": 721},
            {"instructor_lock_screen_minutes": "invalid"},
            [],
        ),
        (
            {"report_recipients": ["a@example.com", "bad", "x@y", "c@example.com"]},
            {"report_recipients": "invalid"},
            [1, 2],
        ),
        (
            {"report_recipients": ["a@example.com", "A@example.com"]},
            {"report_recipients": "duplicate"},
            [],
        ),
        (
            {"gym_name": "", "lock_screen_minutes": 61},
            {"gym_name": "invalid", "lock_screen_minutes": "invalid"},
            [],
        ),
    ],
)
def test_a_broken_field_saves_nothing(
    browser: TestClient,
    db: Session,
    change: dict[str, Any],
    errors: dict[str, str],
    bad_recipients: list[int],
) -> None:
    before = log_entries(db)
    answer = browser.put("/api/settings", json={**FORM, **change})
    assert answer.status_code == 400
    assert answer.json() == {"errors": errors, "bad_recipients": bad_recipients}
    # The good fields in the same form weren't saved either.
    db.rollback()
    assert load_gym_settings(db).manager_email is None
    assert log_entries(db) == before


def test_the_refusal_never_repeats_a_value(browser: TestClient) -> None:
    answer = browser.put(
        "/api/settings", json={**FORM, "manager_email": "secret-person@@example"}
    )
    assert answer.status_code == 400
    assert "secret-person" not in answer.text


@pytest.mark.parametrize(
    "body",
    [
        {k: v for k, v in FORM.items() if k != "gym_name"},
        {**FORM, "gym_name": None},
        {**FORM, "smtp_password": "x"},
        {**FORM, "lock_screen_minutes": "10"},
    ],
    ids=["missing", "gym name cleared", "unknown field", "text minutes"],
)
def test_a_malformed_request_is_a_422(browser: TestClient, body: dict) -> None:
    assert browser.put("/api/settings", json=body).status_code == 422


def test_a_broken_stored_row_is_reported_and_can_be_saved_over(
    browser: TestClient, db: Session
) -> None:
    store_raw(db, "lock_screen_minutes", '"ten"')
    store_raw(db, "report_recipients", "not json")

    answer = browser.get("/api/settings")
    assert answer.status_code == 200
    body = answer.json()
    assert body["problems"] == ["lock_screen_minutes", "report_recipients"]
    # Each broken setting shows its default.
    assert body["lock_screen_minutes"] == 5
    assert body["report_recipients"] == []

    answer = browser.put("/api/settings", json=FORM)
    assert answer.status_code == 200
    assert answer.json()["problems"] == []
    db.rollback()
    assert load_gym_settings(db).lock_screen_minutes == 10


def test_a_row_for_a_removed_setting_is_a_warning_not_a_field(
    browser: TestClient, db: Session
) -> None:
    store_raw(db, "old_setting", "1")
    answer = browser.get("/api/settings")
    assert answer.status_code == 200
    assert answer.json()["problems"] == []
    assert answer.json()["unknown_settings"] is True
