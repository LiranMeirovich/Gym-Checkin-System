"""The activity_log table model: defaults, the checks the database itself
enforces, and that rows can't be changed or deleted. Names are made up."""

from collections.abc import Iterator
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import ActivityLogEntry, StaffUser
from app.core.permissions import Role

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def staff(db: Session) -> StaffUser:
    staff = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_HASH)
    db.add(staff)
    db.commit()
    return staff


def add_entry(db: Session, staff: StaffUser, **values: object) -> ActivityLogEntry:
    entry = ActivityLogEntry(
        staff_user_id=staff.id,
        action="staff.create",
        target_type="staff_user",
        target_id=staff.id,
        **values,
    )
    db.add(entry)
    db.commit()
    return entry


def test_a_new_row_gets_its_defaults(db: Session, staff: StaffUser) -> None:
    entry = add_entry(db, staff)

    assert entry.before_json is None
    assert entry.after_json is None
    assert entry.at.tzinfo is UTC


@pytest.mark.parametrize("column", ["before_json", "after_json"])
def test_the_database_refuses_text_that_isnt_json(
    db: Session, staff: StaffUser, column: str
) -> None:
    with pytest.raises(IntegrityError):
        add_entry(db, staff, **{column: "{not json"})


def test_the_database_refuses_an_unknown_staff_member(db: Session) -> None:
    db.add(ActivityLogEntry(staff_user_id=99, action="staff.create", target_type="x"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE activity_log SET action = 'staff.reset_pin'",
        "DELETE FROM activity_log",
    ],
    ids=["update", "delete"],
)
def test_rows_cant_be_changed_or_deleted(
    db: Session, staff: StaffUser, statement: str
) -> None:
    add_entry(db, staff, after_json='{"role": "manager"}')

    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text(statement))
    db.rollback()

    assert db.scalars(text("SELECT action FROM activity_log")).all() == ["staff.create"]


def test_the_triggers_exist_at_head(db: Session) -> None:
    # A migration that rebuilds the table (batch mode) drops its triggers;
    # it has to create them again.
    triggers = db.scalars(
        text(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'activity_log'"
        )
    ).all()
    assert sorted(triggers) == ["activity_log_no_delete", "activity_log_no_update"]
