"""The wall-QR route of the admin JSON API, on the real admin app: who may
read it and what the printable page gets (decision 0051)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins, wall_qr
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.models import StaffUser
from app.core.permissions import Role
from app.core.staff import create_owner, create_staff_user

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
def owner(db: Session) -> StaffUser:
    staff = create_owner(db, "מנהלת", PIN)
    db.commit()
    return staff


def log_in(client: TestClient, member: StaffUser) -> None:
    answer = client.post(
        "/api/login", json={"staff_id": member.id, "pin": PIN}, headers=SAME_ORIGIN
    )
    assert answer.status_code == 200


def set_hostname(monkeypatch: pytest.MonkeyPatch, hostname: str) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", hostname)
    get_settings.cache_clear()


def test_not_logged_in_gets_401(client: TestClient, owner: StaffUser) -> None:
    assert client.get("/api/wall-qr").status_code == 401


def test_an_instructor_is_refused(
    client: TestClient, db: Session, owner: StaffUser
) -> None:
    member = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=owner)
    db.commit()
    log_in(client, member)

    assert client.get("/api/wall-qr").status_code == 403


def test_a_manager_gets_the_fixed_check_in_address_and_its_qr(
    client: TestClient, db: Session, owner: StaffUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_hostname(monkeypatch, "checkin.example.com")
    manager = create_staff_user(db, "מנהל", Role.MANAGER, PIN, by=owner)
    db.commit()
    log_in(client, manager)

    answer = client.get("/api/wall-qr")

    assert answer.status_code == 200
    assert answer.json() == {
        "url": "https://checkin.example.com/c",
        "qr_image": wall_qr.qr_image("https://checkin.example.com/c"),
    }


def test_nothing_to_print_without_a_public_hostname(
    client: TestClient, owner: StaffUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_hostname(monkeypatch, "")
    log_in(client, owner)

    answer = client.get("/api/wall-qr")

    assert answer.status_code == 200
    assert answer.json() == {"url": None, "qr_image": None}
