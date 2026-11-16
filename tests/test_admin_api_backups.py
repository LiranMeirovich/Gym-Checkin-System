"""The backup route of the admin JSON API, on the real admin app: who may
read it and what the dashboard's card gets."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.api import backups as api_backups
from app.admin.main import app
from app.core import backups, pins
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.models import StaffUser
from app.core.permissions import Role
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
# Made up; real passwords never appear in the repo.
BACKUP_PASSWORD = "not-a-real-backup-password-" + "x" * 8
# 10:00 on 16 November 2026 in Israel (UTC+2).
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_backups, "utc_now", lambda: NOW)


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
    staff = create_owner(db, "מנהלת", PIN)
    db.commit()
    return staff


def log_in(client: TestClient, member: StaffUser) -> None:
    answer = client.post(
        "/api/login", json={"staff_id": member.id, "pin": PIN}, headers=SAME_ORIGIN
    )
    assert answer.status_code == 200


def name_a_backup(made_at: datetime) -> None:
    folder = Path("backups")
    folder.mkdir(exist_ok=True)
    (folder / backups.file_name(made_at)).write_bytes(b"made-up backup")


def test_not_logged_in_gets_401(client: TestClient, owner: StaffUser) -> None:
    assert client.get("/api/backups/latest").status_code == 401


def test_an_instructor_is_refused(
    client: TestClient, db: Session, owner: StaffUser
) -> None:
    member = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=owner)
    db.commit()
    log_in(client, member)

    assert client.get("/api/backups/latest").status_code == 403


def test_a_manager_sees_the_newest_backup(
    client: TestClient, db: Session, owner: StaffUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", BACKUP_PASSWORD)
    get_settings.cache_clear()
    manager = create_staff_user(db, "מנהל", Role.MANAGER, PIN, by=owner)
    db.commit()
    name_a_backup(datetime(2026, 11, 15, 20, 7, 14, tzinfo=UTC))
    name_a_backup(datetime(2026, 11, 16, 7, 2, tzinfo=UTC))
    log_in(client, manager)

    answer = client.get("/api/backups/latest")

    assert answer.status_code == 200
    assert answer.json() == {
        "configured": True,
        "last_backup_at": "2026-11-16T07:02:00Z",
        "overdue": False,
    }


def test_no_backup_yet_is_overdue(client: TestClient, owner: StaffUser) -> None:
    log_in(client, owner)

    answer = client.get("/api/backups/latest")

    # No backup password in this test: backups aren't set up.
    assert answer.json() == {
        "configured": False,
        "last_backup_at": None,
        "overdue": True,
    }
