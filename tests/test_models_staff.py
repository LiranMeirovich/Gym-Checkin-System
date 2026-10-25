"""The staff_users table model: defaults, and the checks the database
itself enforces. Names are made up."""

from collections.abc import Iterator
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import StaffUser
from app.core.permissions import Role

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def insert(db: Session, **values: object) -> None:
    """Insert a row with plain SQL, past the model's own types, the way a
    hand edit or a buggy query would."""
    row = {
        "display_name": "Dana",
        "role": "instructor",
        "pin_hash": FAKE_HASH,
        "failed_attempts": 0,
        "active": True,
        "created_at": "2026-10-25 09:00:00.000000",
        **values,
    }
    db.execute(
        text(
            "INSERT INTO staff_users (display_name, role, pin_hash,"
            " failed_attempts, active, created_at) VALUES (:display_name,"
            " :role, :pin_hash, :failed_attempts, :active, :created_at)"
        ),
        row,
    )
    db.flush()


def test_a_new_row_gets_its_defaults(db: Session) -> None:
    db.add(StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_HASH))
    db.commit()

    row = db.query(StaffUser).one()
    assert row.role is Role.MANAGER
    assert row.failed_attempts == 0
    assert row.locked_until is None
    assert row.active is True
    assert row.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    "values",
    [
        {"role": "owner"},
        {"role": "Manager"},
        {"pin_hash": "482913"},
        {"failed_attempts": -1},
        {"display_name": ""},
        {"display_name": "x" * 51},
        {"active": 2},
    ],
    ids=str,
)
def test_the_database_refuses_bad_values(db: Session, values: dict) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **values)


@pytest.mark.parametrize("second", ["Dana", "dana", "DANA"])
def test_two_active_staff_cannot_share_a_name(db: Session, second: str) -> None:
    insert(db, display_name="Dana")
    with pytest.raises(IntegrityError):
        insert(db, display_name=second)


def test_hebrew_names_are_unique_too(db: Session) -> None:
    insert(db, display_name="דנה")
    with pytest.raises(IntegrityError):
        insert(db, display_name="דנה")


def test_a_deactivated_members_name_can_be_reused(db: Session) -> None:
    insert(db, display_name="Dana", active=False)
    insert(db, display_name="Dana", active=False)
    insert(db, display_name="Dana")


def test_reactivating_into_a_name_clash_is_refused(db: Session) -> None:
    insert(db, display_name="Dana", active=False)
    insert(db, display_name="Dana")
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE staff_users SET active = 1"))
