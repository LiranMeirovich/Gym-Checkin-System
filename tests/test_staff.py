"""Staff accounts: creating, PIN resets, roles, deactivating, and the PIN
check with its lockout. Names and PINs are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import pins, staff
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, StaffUser
from app.core.permissions import Role
from app.core.pins import InvalidPinError, pin_matches
from app.core.staff import (
    DuplicateDisplayNameError,
    InvalidDisplayNameError,
    LastManagerError,
    PinCheck,
    SetupAlreadyDoneError,
    change_role,
    check_pin,
    create_first_manager,
    create_staff_user,
    deactivate,
    reactivate,
    reset_pin,
)

PIN = "482913"
OTHER_PIN = "570461"
START = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cheap Argon2 parameters, so the tests don't spend seconds hashing."""
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(staff, "utc_now", clock)
    return clock


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    return create_first_manager(db, "Noa", PIN)


@pytest.fixture
def instructor(db: Session, manager: StaffUser) -> StaffUser:
    return create_staff_user(db, "Dana", Role.INSTRUCTOR, PIN, by=manager)


# ── Creating ────────────────────────────────────────────────────────────


def test_a_new_staff_member_is_active_with_a_hashed_pin(
    db: Session, manager: StaffUser
) -> None:
    created = create_staff_user(db, "  Dana  ", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()

    row = db.get_one(StaffUser, created.id)
    assert row.display_name == "Dana"
    assert row.role is Role.INSTRUCTOR
    assert row.active
    assert row.pin_hash != PIN
    assert pin_matches(row.pin_hash, PIN)


@pytest.mark.parametrize("name", ["", "   ", "x" * 51])
def test_a_name_must_be_1_to_50_characters(
    db: Session, manager: StaffUser, name: str
) -> None:
    with pytest.raises(InvalidDisplayNameError):
        create_staff_user(db, name, Role.INSTRUCTOR, PIN, by=manager)


@pytest.mark.parametrize(
    "name",
    [
        "Dana​",  # zero-width space
        "Da‍na",  # zero-width joiner
        "‏Dana",  # right-to-left mark
        "Da\x00na",
        "Da\x1bna",
    ],
    ids=ascii,
)
def test_a_name_cannot_hide_invisible_characters(
    db: Session, manager: StaffUser, name: str
) -> None:
    with pytest.raises(InvalidDisplayNameError, match="invisible"):
        create_staff_user(db, name, Role.INSTRUCTOR, PIN, by=manager)


def test_spaces_inside_a_name_are_tidied(db: Session, manager: StaffUser) -> None:
    created = create_staff_user(
        db, " Dana \t  Levi\n", Role.INSTRUCTOR, PIN, by=manager
    )
    assert created.display_name == "Dana Levi"


def test_hebrew_names_are_allowed(db: Session, manager: StaffUser) -> None:
    created = create_staff_user(db, "דנה לוי", Role.INSTRUCTOR, PIN, by=manager)
    assert created.display_name == "דנה לוי"


def test_the_same_letters_typed_two_ways_are_one_name(
    db: Session, manager: StaffUser
) -> None:
    create_staff_user(
        db, "René", Role.INSTRUCTOR, PIN, by=manager
    )  # é as one character
    with pytest.raises(DuplicateDisplayNameError):
        create_staff_user(
            db, "René", Role.INSTRUCTOR, OTHER_PIN, by=manager
        )  # e + accent


@pytest.mark.parametrize("name", ["Dana", "DANA", " dana "])
def test_an_active_name_cannot_be_used_twice(
    db: Session, manager: StaffUser, instructor: StaffUser, name: str
) -> None:
    with pytest.raises(DuplicateDisplayNameError):
        create_staff_user(db, name, Role.MANAGER, OTHER_PIN, by=manager)


def test_a_deactivated_members_name_is_free(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=manager)
    create_staff_user(db, "Dana", Role.INSTRUCTOR, OTHER_PIN, by=manager)


def test_a_bad_pin_adds_nobody(db: Session, manager: StaffUser) -> None:
    with pytest.raises(InvalidPinError):
        create_staff_user(db, "Dana", Role.INSTRUCTOR, "123456", by=manager)
    assert db.scalars(select(StaffUser)).all() == [manager]


# ── PIN reset ───────────────────────────────────────────────────────────


def test_a_reset_pin_replaces_the_old_one(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    reset_pin(db, instructor, OTHER_PIN, by=manager)

    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.OK
    assert check_pin(db, instructor, PIN) is PinCheck.WRONG_PIN


def test_a_reset_lifts_a_lockout(
    db: Session, manager: StaffUser, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)

    reset_pin(db, instructor, OTHER_PIN, by=manager)

    assert instructor.locked_until is None
    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.OK


def test_a_reset_applies_the_format_rules(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    with pytest.raises(InvalidPinError):
        reset_pin(db, instructor, "000000", by=manager)
    assert pin_matches(instructor.pin_hash, PIN)


# ── Roles and the last manager ──────────────────────────────────────────


def test_an_instructor_can_be_promoted(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    change_role(db, instructor, Role.MANAGER, by=manager)
    assert instructor.role is Role.MANAGER


def test_a_manager_can_be_demoted_while_another_remains(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    change_role(db, instructor, Role.MANAGER, by=manager)
    change_role(db, manager, Role.INSTRUCTOR, by=manager)
    assert manager.role is Role.INSTRUCTOR


def test_the_last_manager_cannot_be_demoted(db: Session, manager: StaffUser) -> None:
    with pytest.raises(LastManagerError):
        change_role(db, manager, Role.INSTRUCTOR, by=manager)
    assert manager.role is Role.MANAGER


def test_the_last_manager_cannot_be_deactivated(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    with pytest.raises(LastManagerError):
        deactivate(db, manager, by=manager)
    assert manager.active


def test_the_guard_holds_for_a_role_given_as_text(db: Session) -> None:
    # Built straight from the model with the stored text, the way seed or
    # setup code might; the attribute stays a plain string until reloaded.
    only_manager = StaffUser(
        display_name="Noa", role="manager", pin_hash=pins.hash_pin(PIN)
    )
    db.add(only_manager)
    db.flush()

    with pytest.raises(LastManagerError):
        deactivate(db, only_manager, by=only_manager)
    with pytest.raises(LastManagerError):
        change_role(db, only_manager, Role.INSTRUCTOR, by=only_manager)


def test_an_inactive_manager_does_not_count(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    second = create_staff_user(db, "Yael", Role.MANAGER, OTHER_PIN, by=manager)
    deactivate(db, second, by=manager)

    with pytest.raises(LastManagerError):
        deactivate(db, manager, by=manager)


def test_an_inactive_manager_can_be_demoted(db: Session, manager: StaffUser) -> None:
    second = create_staff_user(db, "Yael", Role.MANAGER, OTHER_PIN, by=manager)
    deactivate(db, second, by=manager)

    change_role(db, second, Role.INSTRUCTOR, by=manager)
    assert second.role is Role.INSTRUCTOR


# ── Deactivating and reactivating ───────────────────────────────────────


def test_deactivating_keeps_the_row(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=manager)
    db.commit()

    assert db.get_one(StaffUser, instructor.id).active is False


def test_a_reactivated_member_can_log_in(
    db: Session, manager: StaffUser, instructor: StaffUser, clock: Clock
) -> None:
    deactivate(db, instructor, by=manager)
    reactivate(db, instructor, by=manager)

    assert check_pin(db, instructor, PIN) is PinCheck.OK


def test_reactivating_into_a_taken_name_is_refused(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=manager)
    create_staff_user(db, "dana", Role.INSTRUCTOR, OTHER_PIN, by=manager)

    with pytest.raises(DuplicateDisplayNameError):
        reactivate(db, instructor, by=manager)
    assert not instructor.active


# ── Checking a PIN ──────────────────────────────────────────────────────


def test_the_right_pin_logs_in(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    assert check_pin(db, instructor, PIN) is PinCheck.OK


def test_a_wrong_pin_counts(db: Session, instructor: StaffUser, clock: Clock) -> None:
    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.WRONG_PIN
    assert instructor.failed_attempts == 1
    assert instructor.locked_until is None


def test_the_right_pin_clears_the_count(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS - 1):
        check_pin(db, instructor, OTHER_PIN)

    assert check_pin(db, instructor, PIN) is PinCheck.OK
    assert instructor.failed_attempts == 0
    # The count started again, so four more wrong PINs don't lock.
    for _ in range(staff.MAX_FAILED_ATTEMPTS - 1):
        assert check_pin(db, instructor, OTHER_PIN) is PinCheck.WRONG_PIN


def test_the_fifth_wrong_pin_locks_for_five_minutes(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    results = [check_pin(db, instructor, OTHER_PIN) for _ in range(5)]

    assert results == [PinCheck.WRONG_PIN] * 4 + [PinCheck.LOCKED]
    assert instructor.locked_until == START + timedelta(minutes=5)


def test_while_locked_even_the_right_pin_is_refused(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)
    clock.now = START + timedelta(minutes=4, seconds=59)

    assert check_pin(db, instructor, PIN) is PinCheck.LOCKED
    # Attempts during a lockout don't count towards the next one.
    assert instructor.failed_attempts == 0


def test_the_lock_ends_after_five_minutes(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)
    clock.now = START + timedelta(minutes=5, seconds=1)

    assert check_pin(db, instructor, PIN) is PinCheck.OK
    assert instructor.locked_until is None


def test_after_a_lock_the_count_starts_again(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)
    clock.now = START + timedelta(minutes=6)

    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.WRONG_PIN


def test_wrong_pins_far_apart_never_lock(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for day in range(10):
        clock.now = START + timedelta(days=day)
        assert check_pin(db, instructor, OTHER_PIN) is PinCheck.WRONG_PIN
    assert instructor.failed_attempts == 1


def test_wrong_pins_within_the_window_of_each_other_add_up(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    # Each one exactly 15 minutes after the last still counts.
    results = []
    for attempt in range(staff.MAX_FAILED_ATTEMPTS):
        clock.now = START + attempt * staff.FAILED_ATTEMPTS_WINDOW
        results.append(check_pin(db, instructor, OTHER_PIN))

    assert results[-1] is PinCheck.LOCKED


def test_a_gap_longer_than_the_window_starts_the_count_again(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS - 1):
        check_pin(db, instructor, OTHER_PIN)
    clock.now = START + staff.FAILED_ATTEMPTS_WINDOW + timedelta(seconds=1)

    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.WRONG_PIN
    assert instructor.failed_attempts == 1
    assert instructor.last_failed_at == clock.now


def test_the_right_pin_clears_the_last_failure(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    check_pin(db, instructor, OTHER_PIN)
    check_pin(db, instructor, PIN)

    assert instructor.last_failed_at is None


def test_an_inactive_member_cannot_log_in(
    db: Session, manager: StaffUser, instructor: StaffUser, clock: Clock
) -> None:
    deactivate(db, instructor, by=manager)

    assert check_pin(db, instructor, PIN) is PinCheck.INACTIVE
    assert instructor.failed_attempts == 0


def test_the_counters_are_saved_with_the_transaction(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    db.commit()
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)
    db.commit()

    with Session(get_engine()) as other:
        row = other.get_one(StaffUser, instructor.id)
        assert row.locked_until == START + timedelta(minutes=5)


# ── Rehashing on login ──────────────────────────────────────────────────


def weak_hash(pin: str) -> str:
    return PasswordHasher(time_cost=1, memory_cost=512, parallelism=1).hash(pin)


def test_the_right_pin_upgrades_an_old_hash(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    instructor.pin_hash = weak_hash(PIN)

    assert check_pin(db, instructor, PIN) is PinCheck.OK
    assert not pins.needs_rehash(instructor.pin_hash)
    assert pin_matches(instructor.pin_hash, PIN)


def test_a_wrong_pin_leaves_an_old_hash_alone(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    old = weak_hash(PIN)
    instructor.pin_hash = old

    check_pin(db, instructor, OTHER_PIN)
    assert instructor.pin_hash == old


def test_a_pin_from_before_a_rules_change_still_works(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    # A PIN the current rules would refuse, set before they existed.
    instructor.pin_hash = weak_hash("111111")

    assert check_pin(db, instructor, "111111") is PinCheck.OK
    assert pin_matches(instructor.pin_hash, "111111")


# ── First-run setup ─────────────────────────────────────────────────────


def test_no_staff_means_setup_is_not_done(db: Session) -> None:
    assert not staff.any_staff_exists(db)


def test_any_staff_member_means_setup_is_done(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=manager)

    assert staff.any_staff_exists(db)


# ── Activity log ────────────────────────────────────────────────────────


def log(db: Session) -> list[tuple]:
    """Every log entry as (actor id, action, target id, before, after)."""
    entries = db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id))
    return [
        (
            entry.staff_user_id,
            entry.action,
            entry.target_id,
            entry.before_json and json.loads(entry.before_json),
            entry.after_json and json.loads(entry.after_json),
        )
        for entry in entries
    ]


def test_the_first_manager_is_logged_as_creating_themselves(db: Session) -> None:
    noa = create_first_manager(db, "Noa", PIN)

    assert log(db) == [
        (
            noa.id,
            "staff.create",
            noa.id,
            None,
            {"display_name": "Noa", "role": "manager", "active": True},
        )
    ]


def test_there_is_only_one_first_manager(db: Session, manager: StaffUser) -> None:
    with pytest.raises(SetupAlreadyDoneError):
        create_first_manager(db, "Yael", OTHER_PIN)
    assert db.scalars(select(StaffUser)).all() == [manager]


def test_creating_a_staff_member_is_logged(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    assert log(db)[-1] == (
        manager.id,
        "staff.create",
        instructor.id,
        None,
        {"display_name": "Dana", "role": "instructor", "active": True},
    )


def test_a_pin_reset_is_logged_without_the_pin(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    reset_pin(db, instructor, OTHER_PIN, by=manager)

    assert log(db)[-1] == (manager.id, "staff.reset_pin", instructor.id, None, None)


def test_no_pin_or_hash_ever_reaches_the_log(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    reset_pin(db, instructor, OTHER_PIN, by=manager)
    change_role(db, instructor, Role.MANAGER, by=manager)
    deactivate(db, instructor, by=manager)
    reactivate(db, instructor, by=manager)

    stored = " ".join(
        f"{entry.before_json} {entry.after_json}"
        for entry in db.scalars(select(ActivityLogEntry))
    )
    for secret in (PIN, OTHER_PIN, "$argon2", instructor.pin_hash):
        assert secret not in stored


def test_a_role_change_is_logged(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    change_role(db, instructor, Role.MANAGER, by=manager)

    assert log(db)[-1] == (
        manager.id,
        "staff.change_role",
        instructor.id,
        {"role": "instructor"},
        {"role": "manager"},
    )


def test_deactivating_and_reactivating_are_logged(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=manager)
    reactivate(db, instructor, by=manager)

    assert log(db)[-2:] == [
        (
            manager.id,
            "staff.deactivate",
            instructor.id,
            {"active": True},
            {"active": False},
        ),
        (
            manager.id,
            "staff.reactivate",
            instructor.id,
            {"active": False},
            {"active": True},
        ),
    ]


def test_changes_that_change_nothing_arent_logged(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    before = log(db)

    change_role(db, instructor, Role.INSTRUCTOR, by=manager)
    reactivate(db, instructor, by=manager)
    deactivate(db, instructor, by=manager)
    deactivate(db, instructor, by=manager)

    assert log(db)[len(before) :] == [
        (
            manager.id,
            "staff.deactivate",
            instructor.id,
            {"active": True},
            {"active": False},
        )
    ]


def test_a_refused_change_isnt_logged(db: Session, manager: StaffUser) -> None:
    before = log(db)

    with pytest.raises(LastManagerError):
        change_role(db, manager, Role.INSTRUCTOR, by=manager)
    with pytest.raises(LastManagerError):
        deactivate(db, manager, by=manager)

    assert log(db) == before


def test_checking_a_pin_isnt_logged(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    before = log(db)

    check_pin(db, instructor, OTHER_PIN)
    check_pin(db, instructor, PIN)

    assert log(db) == before
