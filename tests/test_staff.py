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
from app.core.models import ActivityLogEntry, StaffSession, StaffUser
from app.core.permissions import Role
from app.core.pins import InvalidPinError, pin_matches
from app.core.staff import (
    DuplicateDisplayNameError,
    InvalidDisplayNameError,
    NeedsOwnerError,
    OwnerAccountError,
    PinCheck,
    SetupAlreadyDoneError,
    actions_for,
    change_role,
    check_pin,
    create_owner,
    create_staff_user,
    deactivate,
    locked_until,
    reactivate,
    reset_pin,
)
from app.core.staff_sessions import find_session, start_session

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
def owner(db: Session) -> StaffUser:
    return create_owner(db, "Noa", PIN)


@pytest.fixture
def instructor(db: Session, owner: StaffUser) -> StaffUser:
    return create_staff_user(db, "Dana", Role.INSTRUCTOR, PIN, by=owner)


# ── Creating ────────────────────────────────────────────────────────────


def test_a_new_staff_member_is_active_with_a_hashed_pin(
    db: Session, owner: StaffUser
) -> None:
    created = create_staff_user(db, "  Dana  ", Role.INSTRUCTOR, PIN, by=owner)
    db.commit()

    row = db.get_one(StaffUser, created.id)
    assert row.display_name == "Dana"
    assert row.role is Role.INSTRUCTOR
    assert row.active
    assert row.pin_hash != PIN
    assert pin_matches(row.pin_hash, PIN)


@pytest.mark.parametrize("name", ["", "   ", "x" * 51])
def test_a_name_must_be_1_to_50_characters(
    db: Session, owner: StaffUser, name: str
) -> None:
    with pytest.raises(InvalidDisplayNameError):
        create_staff_user(db, name, Role.INSTRUCTOR, PIN, by=owner)


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
    db: Session, owner: StaffUser, name: str
) -> None:
    with pytest.raises(InvalidDisplayNameError, match="invisible"):
        create_staff_user(db, name, Role.INSTRUCTOR, PIN, by=owner)


def test_spaces_inside_a_name_are_tidied(db: Session, owner: StaffUser) -> None:
    created = create_staff_user(db, " Dana \t  Levi\n", Role.INSTRUCTOR, PIN, by=owner)
    assert created.display_name == "Dana Levi"


def test_hebrew_names_are_allowed(db: Session, owner: StaffUser) -> None:
    created = create_staff_user(db, "דנה לוי", Role.INSTRUCTOR, PIN, by=owner)
    assert created.display_name == "דנה לוי"


def test_the_same_letters_typed_two_ways_are_one_name(
    db: Session, owner: StaffUser
) -> None:
    create_staff_user(db, "René", Role.INSTRUCTOR, PIN, by=owner)  # é as one character
    with pytest.raises(DuplicateDisplayNameError):
        create_staff_user(
            db, "René", Role.INSTRUCTOR, OTHER_PIN, by=owner
        )  # e + accent


@pytest.mark.parametrize("name", ["Dana", "DANA", " dana "])
def test_an_active_name_cannot_be_used_twice(
    db: Session, owner: StaffUser, instructor: StaffUser, name: str
) -> None:
    with pytest.raises(DuplicateDisplayNameError):
        create_staff_user(db, name, Role.MANAGER, OTHER_PIN, by=owner)


def test_a_deactivated_members_name_is_free(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=owner)
    create_staff_user(db, "Dana", Role.INSTRUCTOR, OTHER_PIN, by=owner)


def test_a_bad_pin_adds_nobody(db: Session, owner: StaffUser) -> None:
    with pytest.raises(InvalidPinError):
        create_staff_user(db, "Dana", Role.INSTRUCTOR, "123456", by=owner)
    assert db.scalars(select(StaffUser)).all() == [owner]


# ── PIN reset ───────────────────────────────────────────────────────────


def test_a_reset_pin_replaces_the_old_one(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    reset_pin(db, instructor, OTHER_PIN, by=owner)

    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.OK
    assert check_pin(db, instructor, PIN) is PinCheck.WRONG_PIN


def test_a_reset_lifts_a_lockout(
    db: Session, owner: StaffUser, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)

    reset_pin(db, instructor, OTHER_PIN, by=owner)

    assert instructor.locked_until is None
    assert check_pin(db, instructor, OTHER_PIN) is PinCheck.OK


def test_a_reset_applies_the_format_rules(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    with pytest.raises(InvalidPinError):
        reset_pin(db, instructor, "000000", by=owner)
    assert pin_matches(instructor.pin_hash, PIN)


def test_a_reset_logs_the_member_out_everywhere(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    tokens = [start_session(db, instructor) for _ in range(2)]
    managers_token = start_session(db, owner)

    reset_pin(db, instructor, OTHER_PIN, by=owner)

    assert [find_session(db, token) for token in tokens] == [None, None]
    assert find_session(db, managers_token) is not None


def test_a_reset_of_your_own_pin_keeps_this_session(
    db: Session, owner: StaffUser
) -> None:
    this_token = start_session(db, owner)
    other_token = start_session(db, owner)
    this_session = find_session(db, this_token)
    assert isinstance(this_session, StaffSession)

    reset_pin(db, owner, OTHER_PIN, by=owner, keep_session=this_session)

    assert find_session(db, this_token) is this_session
    assert find_session(db, other_token) is None


# ── The owner, managers and roles ───────────────────────────────────────


@pytest.fixture
def manager(db: Session, owner: StaffUser) -> StaffUser:
    """A manager helping the owner: manages instructors, not managers."""
    return create_staff_user(db, "Yael", Role.MANAGER, PIN, by=owner)


def test_first_run_setup_makes_the_owner(owner: StaffUser) -> None:
    assert owner.role is Role.OWNER


def test_the_owner_can_promote_and_demote(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    change_role(db, instructor, Role.MANAGER, by=owner)
    assert instructor.role is Role.MANAGER

    change_role(db, instructor, Role.INSTRUCTOR, by=owner)
    assert instructor.role is Role.INSTRUCTOR


def test_nobody_else_becomes_the_owner(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    with pytest.raises(OwnerAccountError):
        create_staff_user(db, "Gil", Role.OWNER, OTHER_PIN, by=owner)
    with pytest.raises(OwnerAccountError):
        change_role(db, instructor, Role.OWNER, by=owner)
    assert instructor.role is Role.INSTRUCTOR


@pytest.mark.parametrize("by_owner", [True, False], ids=["by_owner", "by_manager"])
def test_the_owners_account_cannot_be_demoted_or_deactivated(
    db: Session, owner: StaffUser, manager: StaffUser, by_owner: bool
) -> None:
    by = owner if by_owner else manager

    with pytest.raises(OwnerAccountError):
        change_role(db, owner, Role.MANAGER, by=by)
    with pytest.raises(OwnerAccountError):
        deactivate(db, owner, by=by)
    assert (owner.role, owner.active) == (Role.OWNER, True)


def test_only_the_owner_resets_the_owners_pin(
    db: Session, owner: StaffUser, manager: StaffUser
) -> None:
    with pytest.raises(OwnerAccountError):
        reset_pin(db, owner, OTHER_PIN, by=manager)
    assert pin_matches(owner.pin_hash, PIN)

    reset_pin(db, owner, OTHER_PIN, by=owner)
    assert pin_matches(owner.pin_hash, OTHER_PIN)


def test_a_manager_manages_instructors(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    added = create_staff_user(db, "Gil", Role.INSTRUCTOR, OTHER_PIN, by=manager)
    reset_pin(db, instructor, OTHER_PIN, by=manager)
    deactivate(db, instructor, by=manager)
    reactivate(db, instructor, by=manager)

    assert added.role is Role.INSTRUCTOR
    assert instructor.active
    assert pin_matches(instructor.pin_hash, OTHER_PIN)


def test_a_manager_cannot_add_or_make_managers(
    db: Session, manager: StaffUser, instructor: StaffUser
) -> None:
    with pytest.raises(NeedsOwnerError):
        create_staff_user(db, "Gil", Role.MANAGER, OTHER_PIN, by=manager)
    with pytest.raises(NeedsOwnerError):
        change_role(db, instructor, Role.MANAGER, by=manager)
    assert instructor.role is Role.INSTRUCTOR


def test_a_manager_cannot_change_another_managers_account(
    db: Session, owner: StaffUser, manager: StaffUser
) -> None:
    other = create_staff_user(db, "Gil", Role.MANAGER, OTHER_PIN, by=owner)

    with pytest.raises(NeedsOwnerError):
        change_role(db, other, Role.INSTRUCTOR, by=manager)
    with pytest.raises(NeedsOwnerError):
        reset_pin(db, other, PIN, by=manager)
    with pytest.raises(NeedsOwnerError):
        deactivate(db, other, by=manager)
    deactivate(db, other, by=owner)
    with pytest.raises(NeedsOwnerError):
        reactivate(db, other, by=manager)
    assert (other.role, other.active) == (Role.MANAGER, False)


def test_a_manager_cannot_demote_or_deactivate_themselves(
    db: Session, manager: StaffUser
) -> None:
    with pytest.raises(NeedsOwnerError):
        change_role(db, manager, Role.INSTRUCTOR, by=manager)
    with pytest.raises(NeedsOwnerError):
        deactivate(db, manager, by=manager)
    assert (manager.role, manager.active) == (Role.MANAGER, True)


def test_anyone_resets_their_own_pin(db: Session, manager: StaffUser) -> None:
    reset_pin(db, manager, OTHER_PIN, by=manager)
    assert pin_matches(manager.pin_hash, OTHER_PIN)


def test_the_owner_deactivates_a_manager(
    db: Session, owner: StaffUser, manager: StaffUser
) -> None:
    deactivate(db, manager, by=owner)
    assert not manager.active


def test_the_guard_holds_for_a_role_given_as_text(db: Session) -> None:
    # Built straight from the model with the stored text, the way seed or
    # setup code might; the attribute stays a plain string until reloaded.
    owner = StaffUser(display_name="Noa", role="owner", pin_hash=pins.hash_pin(PIN))
    manager = StaffUser(
        display_name="Yael", role="manager", pin_hash=pins.hash_pin(PIN)
    )
    db.add_all([owner, manager])
    db.flush()

    with pytest.raises(OwnerAccountError):
        deactivate(db, owner, by=manager)
    with pytest.raises(NeedsOwnerError):
        deactivate(db, manager, by=manager)


# ── Deactivating and reactivating ───────────────────────────────────────


def test_deactivating_keeps_the_row(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=owner)
    db.commit()

    assert db.get_one(StaffUser, instructor.id).active is False


def test_a_reactivated_member_can_log_in(
    db: Session, owner: StaffUser, instructor: StaffUser, clock: Clock
) -> None:
    deactivate(db, instructor, by=owner)
    reactivate(db, instructor, by=owner)

    assert check_pin(db, instructor, PIN) is PinCheck.OK


def test_reactivating_into_a_taken_name_is_refused(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=owner)
    create_staff_user(db, "dana", Role.INSTRUCTOR, OTHER_PIN, by=owner)

    with pytest.raises(DuplicateDisplayNameError):
        reactivate(db, instructor, by=owner)
    assert not instructor.active


# ── Lockout status ──────────────────────────────────────────────────────


def test_nobody_is_locked_at_first(instructor: StaffUser, clock: Clock) -> None:
    assert locked_until(instructor) is None


def test_a_lockout_shows_until_it_ends(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    for _ in range(staff.MAX_FAILED_ATTEMPTS):
        check_pin(db, instructor, OTHER_PIN)

    assert locked_until(instructor) == START + staff.LOCKOUT
    clock.now = START + staff.LOCKOUT
    assert locked_until(instructor) is None


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
    db: Session, owner: StaffUser, instructor: StaffUser, clock: Clock
) -> None:
    deactivate(db, instructor, by=owner)

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
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=owner)

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


def test_the_owner_is_logged_as_creating_themselves(db: Session) -> None:
    noa = create_owner(db, "Noa", PIN)

    assert log(db) == [
        (
            noa.id,
            "staff.create",
            noa.id,
            None,
            {"display_name": "Noa", "role": "owner", "active": True},
        )
    ]


def test_there_is_only_one_first_run_owner(db: Session, owner: StaffUser) -> None:
    with pytest.raises(SetupAlreadyDoneError):
        create_owner(db, "Yael", OTHER_PIN)
    assert db.scalars(select(StaffUser)).all() == [owner]


def test_creating_a_staff_member_is_logged(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    assert log(db)[-1] == (
        owner.id,
        "staff.create",
        instructor.id,
        None,
        {"display_name": "Dana", "role": "instructor", "active": True},
    )


def test_a_pin_reset_is_logged_without_the_pin(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    reset_pin(db, instructor, OTHER_PIN, by=owner)

    assert log(db)[-1] == (owner.id, "staff.reset_pin", instructor.id, None, None)


def test_no_pin_or_hash_ever_reaches_the_log(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    reset_pin(db, instructor, OTHER_PIN, by=owner)
    change_role(db, instructor, Role.MANAGER, by=owner)
    deactivate(db, instructor, by=owner)
    reactivate(db, instructor, by=owner)

    stored = " ".join(
        f"{entry.before_json} {entry.after_json}"
        for entry in db.scalars(select(ActivityLogEntry))
    )
    for secret in (PIN, OTHER_PIN, "$argon2", instructor.pin_hash):
        assert secret not in stored


def test_a_role_change_is_logged(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    change_role(db, instructor, Role.MANAGER, by=owner)

    assert log(db)[-1] == (
        owner.id,
        "staff.change_role",
        instructor.id,
        {"role": "instructor"},
        {"role": "manager"},
    )


def test_deactivating_and_reactivating_are_logged(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    deactivate(db, instructor, by=owner)
    reactivate(db, instructor, by=owner)

    assert log(db)[-2:] == [
        (
            owner.id,
            "staff.deactivate",
            instructor.id,
            {"active": True},
            {"active": False},
        ),
        (
            owner.id,
            "staff.reactivate",
            instructor.id,
            {"active": False},
            {"active": True},
        ),
    ]


def test_changes_that_change_nothing_arent_logged(
    db: Session, owner: StaffUser, instructor: StaffUser
) -> None:
    before = log(db)

    change_role(db, instructor, Role.INSTRUCTOR, by=owner)
    reactivate(db, instructor, by=owner)
    deactivate(db, instructor, by=owner)
    deactivate(db, instructor, by=owner)

    assert log(db)[len(before) :] == [
        (
            owner.id,
            "staff.deactivate",
            instructor.id,
            {"active": True},
            {"active": False},
        )
    ]


def test_a_refused_change_isnt_logged(db: Session, owner: StaffUser) -> None:
    before = log(db)

    with pytest.raises(OwnerAccountError):
        change_role(db, owner, Role.INSTRUCTOR, by=owner)
    with pytest.raises(OwnerAccountError):
        deactivate(db, owner, by=owner)

    assert log(db) == before


def test_checking_a_pin_isnt_logged(
    db: Session, instructor: StaffUser, clock: Clock
) -> None:
    before = log(db)

    check_pin(db, instructor, OTHER_PIN)
    check_pin(db, instructor, PIN)

    assert log(db) == before


# ── What the Staff screen offers ────────────────────────────────────────


def offered(by: StaffUser, member: StaffUser) -> tuple[bool, bool, bool]:
    may = actions_for(by, member)
    return (may.reset_pin, may.change_role, may.toggle_active)


def test_the_owner_may_do_everything_but_change_their_own_account(
    db: Session, owner: StaffUser, manager: StaffUser, instructor: StaffUser
) -> None:
    assert offered(owner, owner) == (True, False, False)
    assert offered(owner, manager) == (True, True, True)
    assert offered(owner, instructor) == (True, True, True)


def test_a_manager_is_offered_instructors_and_their_own_pin(
    db: Session, owner: StaffUser, manager: StaffUser, instructor: StaffUser
) -> None:
    other = create_staff_user(db, "Gil", Role.MANAGER, OTHER_PIN, by=owner)

    assert offered(manager, owner) == (False, False, False)
    assert offered(manager, other) == (False, False, False)
    assert offered(manager, manager) == (True, False, False)
    # Promoting an instructor makes a manager: the owner's to do.
    assert offered(manager, instructor) == (True, False, True)


def try_action(db: Session, action: str, by: StaffUser, member: StaffUser) -> bool:
    """Whether the change behind ``action`` goes through; undone either way."""
    savepoint = db.begin_nested()
    try:
        if action == "reset_pin":
            reset_pin(db, member, OTHER_PIN, by=by)
        elif action == "change_role":
            other = Role.INSTRUCTOR if member.role == Role.MANAGER else Role.MANAGER
            change_role(db, member, other, by=by)
        else:
            deactivate(db, member, by=by)
    except (OwnerAccountError, NeedsOwnerError):
        return False
    finally:
        savepoint.rollback()
    return True


def test_what_is_offered_matches_what_is_allowed(
    db: Session, owner: StaffUser, manager: StaffUser, instructor: StaffUser
) -> None:
    other = create_staff_user(db, "Gil", Role.MANAGER, OTHER_PIN, by=owner)
    for by in (owner, manager):
        for member in (owner, manager, other, instructor):
            may = actions_for(by, member)
            for action in ("reset_pin", "change_role", "toggle_active"):
                allowed = try_action(db, action, by, member)
                assert allowed is getattr(may, action), (by.id, member.id, action)
