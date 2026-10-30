"""The price routes of the admin JSON API, on the real admin app: what each
role may do, the answers and error codes, and that refused requests save
nothing. Amounts are made up."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import months, pins
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, Price, StaffUser
from app.core.permissions import Role
from app.core.staff import create_first_manager, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
MONTHLY_ADULT = {"plan": "monthly", "age_group": "adult", "amount_agorot": 25000}
SAVE = {"valid_from_month": "2026-10", "prices": [MONTHLY_ADULT]}


@pytest.fixture(autouse=True)
def fixed_month(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    )


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

    def get(self):
        return self.client.get("/api/prices")

    def post(self, json: object):
        return self.client.post("/api/prices", json=json, headers=self.headers)


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


def rows_in_db(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Price))


# Who may do what


def test_not_logged_in_gets_401(client: TestClient, manager: StaffUser) -> None:
    assert client.get("/api/prices").status_code == 401
    answer = client.post("/api/prices", json=SAVE, headers=SAME_ORIGIN)
    assert answer.status_code == 401


def test_an_instructor_can_view_prices(as_instructor: Staff) -> None:
    assert as_instructor.get().status_code == 200


def test_an_instructor_cant_change_prices(as_instructor: Staff, db: Session) -> None:
    assert as_instructor.post(SAVE).status_code == 403
    assert rows_in_db(db) == 0


def test_a_change_needs_the_csrf_token(as_manager: Staff, db: Session) -> None:
    answer = as_manager.client.post("/api/prices", json=SAVE, headers=SAME_ORIGIN)
    assert answer.status_code == 403
    assert rows_in_db(db) == 0


# The answers


def test_an_empty_table(as_manager: Staff) -> None:
    answer = as_manager.get()

    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "no-store"
    body = answer.json()
    assert body["current_month"] == "2026-10"
    assert len(body["current"]) == 6
    assert body["current"][0] == {
        "plan": "monthly",
        "age_group": "adult",
        "amount_agorot": None,
        "valid_from_month": None,
    }
    assert body["upcoming"] == []
    assert body["history"] == []


def test_a_save_answers_with_the_updated_overview(as_manager: Staff) -> None:
    answer = as_manager.post(
        {
            "valid_from_month": "2026-11",
            "prices": [
                MONTHLY_ADULT,
                {
                    "plan": "single_entry",
                    "age_group": "under_18",
                    "amount_agorot": 3050,
                },
            ],
        }
    )

    assert answer.status_code == 201
    body = answer.json()
    assert body["current"][0]["amount_agorot"] is None
    assert [
        (r["plan"], r["amount_agorot"], r["valid_from_month"]) for r in body["upcoming"]
    ] == [("monthly", 25000, "2026-11"), ("single_entry", 3050, "2026-11")]
    assert len(body["history"]) == 2
    # The gym's local time, with its offset: winter or summer time in Israel,
    # since the row is stamped by the real clock.
    created_at = datetime.fromisoformat(body["history"][0]["created_at"])
    assert created_at.utcoffset() in {timedelta(hours=2), timedelta(hours=3)}


def test_this_months_price_shows_as_current(as_manager: Staff) -> None:
    body = as_manager.post(SAVE).json()

    assert body["current"][0] == {**MONTHLY_ADULT, "valid_from_month": "2026-10"}
    assert body["upcoming"] == []


def test_a_correction_stays_in_the_history(as_manager: Staff) -> None:
    as_manager.post(SAVE)
    body = as_manager.post(
        {**SAVE, "prices": [{**MONTHLY_ADULT, "amount_agorot": 26000}]}
    ).json()

    assert body["current"][0]["amount_agorot"] == 26000
    assert [r["amount_agorot"] for r in body["history"]] == [26000, 25000]


def test_a_change_is_logged_against_the_acting_manager(
    as_manager: Staff, manager: StaffUser, db: Session
) -> None:
    as_manager.post(SAVE)

    entry = db.scalar(
        select(ActivityLogEntry).where(ActivityLogEntry.target_type == "price")
    )
    assert entry.action == "price.add"
    assert entry.staff_user_id == manager.id


# Refusals


def test_a_broken_save_names_every_part_and_saves_nothing(
    as_manager: Staff, db: Session
) -> None:
    answer = as_manager.post(
        {
            "valid_from_month": "2026-09",
            "prices": [
                MONTHLY_ADULT,
                {**MONTHLY_ADULT, "plan": "tri_monthly", "amount_agorot": 0},
            ],
        }
    )

    assert answer.status_code == 400
    assert answer.json() == {
        "errors": {"valid_from_month": "invalid", "tri_monthly.adult": "invalid"}
    }
    assert rows_in_db(db) == 0


@pytest.mark.parametrize(
    "bad",
    [
        {**SAVE, "valid_from_month": "2026-13"},
        {**SAVE, "valid_from_month": "2026-10-01"},
        {**SAVE, "valid_from_month": "0999-01"},
        {**SAVE, "valid_from_month": "2026-10\n"},
        {**SAVE, "prices": [{**MONTHLY_ADULT, "plan": "weekly"}]},
        {**SAVE, "prices": [{**MONTHLY_ADULT, "age_group": "senior"}]},
        {**SAVE, "prices": [{**MONTHLY_ADULT, "amount_agorot": "25000"}]},
        {**SAVE, "prices": [{**MONTHLY_ADULT, "amount_agorot": 250.5}]},
        {"prices": [MONTHLY_ADULT]},
    ],
)
def test_a_malformed_request_is_a_422(
    as_manager: Staff, db: Session, bad: dict[str, object]
) -> None:
    assert as_manager.post(bad).status_code == 422
    assert rows_in_db(db) == 0
