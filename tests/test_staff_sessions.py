"""Staff login sessions: the table's own checks, and starting, finding and
ending sessions with their timeouts. Names are made up."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import staff_sessions
from app.core.db import get_engine
from app.core.gym_settings import update_gym_settings
from app.core.models import Setting, StaffSession, StaffUser
from app.core.permissions import Role
from app.core.staff_sessions import (
    MAX_SESSION_AGE,
    end_session,
    find_session,
    hash_token,
    idle_timeout,
    lock_settings,
    start_session,
    touch,
)

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
START = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(staff_sessions, "utc_now", clock)
    return clock


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def dana(db: Session) -> StaffUser:
    """A manager, so the idle timeout below is the 5-minute one."""
    staff = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH)
    db.add(staff)
    db.flush()
    return staff


# ── The table ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "token_hash",
    ["a-plain-token", "A" * 64, "a" * 63, "a" * 65, "g" * 64],
    ids=["plain", "uppercase", "short", "long", "not-hex"],
)
def test_only_a_sha256_hex_digest_can_be_stored(
    db: Session, dana: StaffUser, token_hash: str
) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO staff_sessions (staff_user_id, token_hash,"
                " created_at, last_seen_at) VALUES (:staff, :hash,"
                " '2026-10-25 09:00:00.000000', '2026-10-25 09:00:00.000000')"
            ),
            {"staff": dana.id, "hash": token_hash},
        )


def test_a_session_must_belong_to_a_staff_member(db: Session) -> None:
    db.add(StaffSession(staff_user_id=999, token_hash=hash_token("x")))

    with pytest.raises(IntegrityError):
        db.flush()


# ── Starting ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("clock")
def test_starting_stores_only_the_hash_of_the_token(
    db: Session, dana: StaffUser
) -> None:
    token = start_session(db, dana)

    row = db.scalars(select(StaffSession)).one()
    assert row.token_hash == hash_token(token)
    assert token not in row.token_hash
    assert row.staff_user_id == dana.id
    assert row.created_at == row.last_seen_at == START
    assert row.ended_at is None


@pytest.mark.usefixtures("clock")
def test_every_session_gets_a_new_random_token(db: Session, dana: StaffUser) -> None:
    tokens = {start_session(db, dana) for _ in range(5)}

    assert len(tokens) == 5
    # 32 random bytes, URL-safe base64.
    assert all(len(token) >= 43 for token in tokens)


# ── Finding ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("clock")
def test_the_token_finds_its_session(db: Session, dana: StaffUser) -> None:
    token = start_session(db, dana)

    session = find_session(db, token)

    assert session is not None
    assert session.staff is dana


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("token", ["", "not-a-token", "a" * 4000])
def test_an_unknown_token_finds_nothing(
    db: Session, dana: StaffUser, token: str
) -> None:
    start_session(db, dana)

    assert find_session(db, token) is None


@pytest.mark.usefixtures("clock")
def test_the_stored_hash_is_not_a_token(db: Session, dana: StaffUser) -> None:
    # Someone with a copy of the database can't use what's stored there.
    start_session(db, dana)
    stored = db.scalars(select(StaffSession.token_hash)).one()

    assert find_session(db, stored) is None


def test_a_session_idle_up_to_the_lock_time_still_counts(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)

    clock.now += timedelta(minutes=5)

    assert find_session(db, token) is not None


def test_a_session_idle_past_the_lock_time_is_refused(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)

    clock.now += timedelta(minutes=5, seconds=1)

    assert find_session(db, token) is None


def test_the_lock_time_comes_from_the_gym_settings(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    update_gym_settings(db, {"lock_screen_minutes": 15}, by=dana)
    token = start_session(db, dana)

    clock.now += timedelta(minutes=14)
    assert find_session(db, token) is not None
    clock.now += timedelta(minutes=2)
    assert find_session(db, token) is None


def test_an_instructor_gets_the_instructor_lock_time(db: Session, clock: Clock) -> None:
    tal = StaffUser(display_name="Tal", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH)
    db.add(tal)
    db.flush()
    token = start_session(db, tal)

    clock.now += timedelta(minutes=60)
    assert find_session(db, token) is not None
    clock.now += timedelta(seconds=1)
    assert find_session(db, token) is None


def test_each_roles_lock_time_comes_from_its_own_setting(
    db: Session, dana: StaffUser
) -> None:
    update_gym_settings(
        db, {"lock_screen_minutes": 3, "instructor_lock_screen_minutes": 90}, by=dana
    )

    settings = lock_settings(db)

    assert idle_timeout(settings, Role.MANAGER) == timedelta(minutes=3)
    assert idle_timeout(settings, Role.INSTRUCTOR) == timedelta(minutes=90)
    # The stored text works too.
    assert idle_timeout(settings, "instructor") == timedelta(minutes=90)


def test_a_broken_settings_row_falls_back_to_the_default_lock_time(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    # A row no setting accepts: the manager must still be able to log in
    # and repair it from the settings screen.
    db.add(Setting(key="lock_screen_minutes", value='"five"', updated_at=START))
    db.add(Setting(key="report_recipients", value="not json", updated_at=START))
    db.flush()
    token = start_session(db, dana)

    clock.now += timedelta(minutes=5)
    assert find_session(db, token) is not None
    clock.now += timedelta(minutes=1)
    assert find_session(db, token) is None


def test_a_role_change_switches_the_lock_time(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)
    clock.now += timedelta(minutes=10)
    assert find_session(db, token) is None

    dana.role = Role.INSTRUCTOR
    db.flush()

    assert find_session(db, token) is not None


def test_activity_restarts_the_idle_timeout(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)

    for _ in range(3):
        clock.now += timedelta(minutes=4)
        session = find_session(db, token)
        assert session is not None
        touch(db, session)

    assert session.last_seen_at == clock.now


def test_finding_alone_doesnt_count_as_activity(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)

    clock.now += timedelta(minutes=4)
    find_session(db, token)
    clock.now += timedelta(minutes=4)

    assert find_session(db, token) is None


def test_an_active_session_still_ends_after_the_maximum_age(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)

    # Busy all day: never idle, but too old in the end.
    while clock.now - START < MAX_SESSION_AGE:
        clock.now += timedelta(minutes=4)
        session = find_session(db, token)
        assert session is not None
        touch(db, session)
    clock.now += timedelta(minutes=1)

    assert find_session(db, token) is None


@pytest.mark.usefixtures("clock")
def test_a_deactivated_staff_members_session_is_refused(
    db: Session, dana: StaffUser
) -> None:
    token = start_session(db, dana)

    dana.active = False
    db.flush()

    assert find_session(db, token) is None


@pytest.mark.usefixtures("clock")
def test_other_sessions_are_unaffected(db: Session, dana: StaffUser) -> None:
    noa = StaffUser(display_name="Noa", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH)
    db.add(noa)
    db.flush()
    danas = start_session(db, dana)
    noas = start_session(db, noa)

    end_session(db, find_session(db, danas))

    assert find_session(db, danas) is None
    found = find_session(db, noas)
    assert found is not None
    assert found.staff is noa


# ── Ending ──────────────────────────────────────────────────────────────


def test_an_ended_session_is_refused_and_kept(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)
    session = find_session(db, token)

    end_session(db, session)

    assert find_session(db, token) is None
    assert session.ended_at == START
    assert db.scalars(select(StaffSession)).one() is session


def test_ending_twice_keeps_the_first_end_time(
    db: Session, dana: StaffUser, clock: Clock
) -> None:
    token = start_session(db, dana)
    session = find_session(db, token)
    end_session(db, session)

    clock.now += timedelta(minutes=1)
    end_session(db, session)

    assert session.ended_at == START
