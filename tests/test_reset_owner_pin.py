"""The owner PIN reset command (decision 0050). Names and PINs are made up."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import reset_owner_pin as command
from app.core import pins, staff
from app.core.activity_log import Action
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, StaffUser
from app.core.permissions import Role
from app.core.pins import InvalidPinError, pin_matches
from app.core.staff_sessions import find_session, start_session

PIN = "482913"
NEW_PIN = "570461"


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
    owner = staff.create_owner(db, "Noa", PIN)
    db.commit()
    return owner


@pytest.fixture
def manager(db: Session, owner: StaffUser) -> StaffUser:
    manager = staff.create_staff_user(db, "Ron", Role.MANAGER, PIN, by=owner)
    db.commit()
    return manager


def fresh(db: Session, member: StaffUser) -> StaffUser:
    db.expire_all()
    return db.get_one(StaffUser, member.id)


def typed(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    """What the person at the server types at the two hidden prompts."""
    replies = iter(answers)
    monkeypatch.setattr(command.getpass, "getpass", lambda _prompt: next(replies))


def test_the_owners_pin_is_replaced(db: Session, owner: StaffUser) -> None:
    name = command.reset_owner_pin(NEW_PIN)

    assert name == "Noa"
    assert pin_matches(fresh(db, owner).pin_hash, NEW_PIN)


def test_only_the_owners_pin_changes(
    db: Session, owner: StaffUser, manager: StaffUser
) -> None:
    command.reset_owner_pin(NEW_PIN)

    assert pin_matches(fresh(db, manager).pin_hash, PIN)


def test_it_lifts_a_lockout(db: Session, owner: StaffUser) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        staff.check_pin(db, owner, "111222")
    db.commit()
    assert staff.locked_until(owner) is not None

    command.reset_owner_pin(NEW_PIN)

    assert fresh(db, owner).locked_until is None


def test_it_ends_the_owners_sessions_only(
    db: Session, owner: StaffUser, manager: StaffUser
) -> None:
    owners = start_session(db, owner)
    managers = start_session(db, manager)
    db.commit()

    command.reset_owner_pin(NEW_PIN)

    db.expire_all()
    assert find_session(db, owners) is None
    assert find_session(db, managers) is not None


def test_it_is_logged_as_the_owner_without_the_pin(
    db: Session, owner: StaffUser
) -> None:
    command.reset_owner_pin(NEW_PIN)

    entry = db.scalars(
        select(ActivityLogEntry).order_by(ActivityLogEntry.id.desc())
    ).first()
    assert entry is not None
    assert entry.action == Action.STAFF_RESET_PIN
    assert entry.staff_user_id == owner.id
    assert entry.target_id == owner.id
    logged = json.dumps([entry.before_json, entry.after_json])
    assert NEW_PIN not in logged
    assert "argon2" not in logged


def test_a_pin_breaking_the_rules_changes_nothing(
    db: Session, owner: StaffUser
) -> None:
    with pytest.raises(InvalidPinError):
        command.reset_owner_pin("123456")

    assert pin_matches(fresh(db, owner).pin_hash, PIN)


@pytest.mark.usefixtures("migrated_db")
def test_before_first_run_setup_there_is_no_owner() -> None:
    with pytest.raises(command.NoOwnerError, match="first-run setup"):
        command.reset_owner_pin(NEW_PIN)


def test_the_command_resets_after_the_pin_is_typed_twice(
    db: Session,
    owner: StaffUser,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    typed(monkeypatch, NEW_PIN, NEW_PIN)

    command.main()

    assert pin_matches(fresh(db, owner).pin_hash, NEW_PIN)
    out = capsys.readouterr().out
    assert "is reset" in out
    assert NEW_PIN not in out


def test_the_command_refuses_two_different_pins(
    db: Session, owner: StaffUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    typed(monkeypatch, NEW_PIN, "570462")

    with pytest.raises(SystemExit, match="don't match"):
        command.main()

    assert pin_matches(fresh(db, owner).pin_hash, PIN)


def test_the_command_names_a_broken_rule(
    db: Session, owner: StaffUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    typed(monkeypatch, "000000", "000000")

    with pytest.raises(SystemExit, match="one digit repeated"):
        command.main()

    assert pin_matches(fresh(db, owner).pin_hash, PIN)


def test_the_command_refuses_a_missing_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    typed(monkeypatch)  # never asked: the database is checked first

    with pytest.raises(SystemExit, match="no database"):
        command.main()
