"""The activity log and staff list routes of the admin JSON API, on the real
admin app: who may read them, the answers, and the query checks. Names are
made up."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, StaffUser
from app.core.permissions import Role
from app.core.staff import create_first_manager, create_staff_user, deactivate

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"


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


def log_in(client: TestClient, member: StaffUser) -> TestClient:
    answer = client.post(
        "/api/login", json={"staff_id": member.id, "pin": PIN}, headers=SAME_ORIGIN
    )
    assert answer.status_code == 200
    return client


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> TestClient:
    return log_in(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> TestClient:
    return log_in(client, instructor)


# Who may read them


@pytest.mark.parametrize("path", ["/api/activity-log", "/api/staff"])
def test_not_logged_in_gets_401(
    client: TestClient, manager: StaffUser, path: str
) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/api/activity-log", "/api/staff"])
def test_an_instructor_is_refused(as_instructor: TestClient, path: str) -> None:
    assert as_instructor.get(path).status_code == 403


# The activity log


def test_the_log_shows_who_did_what_newest_first(
    as_manager: TestClient, manager: StaffUser, instructor: StaffUser
) -> None:
    answer = as_manager.get("/api/activity-log")

    assert answer.status_code == 200
    body = answer.json()
    newest, oldest = body["entries"]
    assert newest["action"] == "staff.create"
    assert newest["staff"] == {"id": manager.id, "display_name": "מנהלת"}
    assert newest["target_type"] == "staff_user"
    assert newest["target_id"] == instructor.id
    assert newest["target_name"] == "מדריך"
    assert newest["before"] is None
    assert newest["after"]["role"] == "instructor"
    # The first manager is their own actor (decision 0021).
    assert oldest["target_id"] == manager.id
    assert body["next_before_id"] is None


def test_times_are_the_gyms_local_time(
    as_manager: TestClient, db: Session, manager: StaffUser
) -> None:
    db.add(
        ActivityLogEntry(
            staff_user_id=manager.id,
            action="settings.update",
            target_type="settings",
            at=datetime(2026, 11, 8, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    [entry] = as_manager.get(
        "/api/activity-log", params={"target_type": "settings"}
    ).json()["entries"]

    assert entry["at"] == "2026-11-08T12:00:00+02:00"


def test_the_filters_reach_the_query(
    as_manager: TestClient, manager: StaffUser, instructor: StaffUser
) -> None:
    def ids(**params: object) -> list[int | None]:
        answer = as_manager.get("/api/activity-log", params=params)
        assert answer.status_code == 200
        return [e["target_id"] for e in answer.json()["entries"]]

    assert ids(target_type="staff_user", target_id=instructor.id) == [instructor.id]
    assert ids(staff_id=instructor.id) == []
    assert ids(**{"from": "2000-01-01", "to": "2000-01-31"}) == []
    assert len(ids(**{"from": "2000-01-01"})) == 2


def test_before_id_pages_back(
    as_manager: TestClient, db: Session, manager: StaffUser
) -> None:
    for _ in range(60):
        db.add(
            ActivityLogEntry(
                staff_user_id=manager.id,
                action="settings.update",
                target_type="settings",
            )
        )
    db.commit()

    first = as_manager.get("/api/activity-log").json()
    second = as_manager.get(
        "/api/activity-log", params={"before_id": first["next_before_id"]}
    ).json()

    # 61 entries: the 60 above and the first manager's own creation.
    assert len(first["entries"]) == 50
    assert len(second["entries"]) == 11
    assert second["next_before_id"] is None
    assert first["entries"][-1]["id"] > second["entries"][0]["id"]


def test_an_older_shape_comes_back_as_stored(
    as_manager: TestClient, db: Session, manager: StaffUser
) -> None:
    db.add(
        ActivityLogEntry(
            staff_user_id=manager.id,
            action="price.add",
            target_type="price",
            target_id=1,
            after_json='{"age_group": "under_18", "amount_agorot": 15000}',
        )
    )
    db.commit()

    [entry] = as_manager.get(
        "/api/activity-log", params={"target_type": "price"}
    ).json()["entries"]

    assert entry["after"] == {"age_group": "under_18", "amount_agorot": 15000}
    assert entry["target_name"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"target_id": 1},
        {"staff_id": 0},
        {"before_id": "x"},
        {"from": "2026-13-01"},
        {"target_type": ""},
        {"unknown": "1"},
    ],
    ids=str,
)
def test_malformed_queries_are_refused(
    as_manager: TestClient, params: dict[str, object]
) -> None:
    assert as_manager.get("/api/activity-log", params=params).status_code == 422


# The staff list


def test_the_staff_list_has_everyone_active_first(
    as_manager: TestClient, db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    other = create_staff_user(db, "אורי", Role.INSTRUCTOR, PIN, by=manager)
    deactivate(db, other, by=manager)
    db.commit()

    answer = as_manager.get("/api/staff")

    assert answer.status_code == 200
    assert answer.json()["staff"] == [
        {
            "id": instructor.id,
            "display_name": "מדריך",
            "role": "instructor",
            "active": True,
        },
        {"id": manager.id, "display_name": "מנהלת", "role": "manager", "active": True},
        {"id": other.id, "display_name": "אורי", "role": "instructor", "active": False},
    ]
