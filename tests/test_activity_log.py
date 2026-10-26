"""Writing activity log entries. Names are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
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
def actor(db: Session) -> StaffUser:
    staff = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_HASH)
    db.add(staff)
    db.commit()
    return staff


def entries(db: Session) -> list[ActivityLogEntry]:
    return list(db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id)))


def test_record_writes_who_what_and_the_change(db: Session, actor: StaffUser) -> None:
    record(
        db,
        actor,
        Action.STAFF_CHANGE_ROLE,
        Target.STAFF_USER,
        7,
        before={"role": "instructor"},
        after={"role": "manager"},
    )
    db.commit()

    [entry] = entries(db)
    assert entry.staff_user_id == actor.id
    assert entry.action == "staff.change_role"
    assert entry.target_type == "staff_user"
    assert entry.target_id == 7
    assert json.loads(entry.before_json) == {"role": "instructor"}
    assert json.loads(entry.after_json) == {"role": "manager"}
    assert entry.at.tzinfo is UTC


def test_before_after_and_target_id_can_be_left_out(
    db: Session, actor: StaffUser
) -> None:
    record(db, actor, Action.SETTINGS_UPDATE, Target.SETTINGS)
    db.commit()

    [entry] = entries(db)
    assert entry.target_id is None
    assert entry.before_json is None
    assert entry.after_json is None


def test_json_is_sorted_and_keeps_hebrew_readable(
    db: Session, actor: StaffUser
) -> None:
    record(
        db,
        actor,
        Action.SETTINGS_UPDATE,
        Target.SETTINGS,
        after={"lock_screen_minutes": 10, "gym_name": "מכון לדוגמה"},
    )

    [entry] = entries(db)
    assert entry.after_json == '{"gym_name": "מכון לדוגמה", "lock_screen_minutes": 10}'


def test_record_doesnt_commit(db: Session, actor: StaffUser) -> None:
    record(db, actor, Action.SETTINGS_UPDATE, Target.SETTINGS)
    db.rollback()

    assert entries(db) == []


@pytest.mark.parametrize(
    "value", [datetime(2026, 10, 26, tzinfo=UTC), float("nan")], ids=str
)
def test_values_that_arent_plain_json_are_refused(
    db: Session, actor: StaffUser, value: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        record(db, actor, Action.SETTINGS_UPDATE, Target.SETTINGS, after={"x": value})


def test_unknown_actions_and_targets_are_refused(db: Session, actor: StaffUser) -> None:
    with pytest.raises(ValueError):
        record(db, actor, "staff.fire", Target.STAFF_USER)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        record(db, actor, Action.STAFF_CREATE, "customer")  # type: ignore[arg-type]


def test_an_actor_without_an_id_is_refused(db: Session) -> None:
    unsaved = StaffUser(display_name="Noa", role=Role.MANAGER, pin_hash=FAKE_HASH)

    with pytest.raises(ValueError, match="no id"):
        record(db, unsaved, Action.STAFF_CREATE, Target.STAFF_USER)
