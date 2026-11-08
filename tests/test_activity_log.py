"""Writing activity log entries. Names are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, list_entries, record
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, Customer, StaffUser
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
        record(db, actor, Action.STAFF_CREATE, "gym_door")  # type: ignore[arg-type]


def test_an_actor_without_an_id_is_refused(db: Session) -> None:
    unsaved = StaffUser(display_name="Noa", role=Role.MANAGER, pin_hash=FAKE_HASH)

    with pytest.raises(ValueError, match="no id"):
        record(db, unsaved, Action.STAFF_CREATE, Target.STAFF_USER)


# ── Reading the log ─────────────────────────────────────────────────────


def add_entry(
    db: Session,
    actor: StaffUser,
    *,
    at: datetime | None = None,
    action: str = "settings.update",
    target_type: str = "settings",
    target_id: int | None = None,
    before_json: str | None = None,
    after_json: str | None = None,
) -> ActivityLogEntry:
    """A row written directly, so tests can pick its time and shape
    (including shapes ``record()`` no longer writes)."""
    entry = ActivityLogEntry(
        staff_user_id=actor.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_json=before_json,
        after_json=after_json,
        **({} if at is None else {"at": at}),
    )
    db.add(entry)
    db.flush()
    return entry


def test_entries_come_newest_first_with_the_actors_name(
    db: Session, actor: StaffUser
) -> None:
    first = record(db, actor, Action.SETTINGS_UPDATE, Target.SETTINGS)
    second = record(
        db,
        actor,
        Action.STAFF_CHANGE_ROLE,
        Target.STAFF_USER,
        actor.id,
        before={"role": "instructor"},
        after={"role": "manager"},
    )

    page = list_entries(db)

    assert [e.id for e in page.entries] == [second.id, first.id]
    newest = page.entries[0]
    assert newest.staff_name == "Dana"
    assert newest.action == "staff.change_role"
    assert newest.before == {"role": "instructor"}
    assert newest.after == {"role": "manager"}
    assert page.next_before_id is None


def test_pages_continue_from_before_id(db: Session, actor: StaffUser) -> None:
    ids = [add_entry(db, actor).id for _ in range(5)]

    first = list_entries(db, limit=2)
    second = list_entries(db, limit=2, before_id=first.next_before_id)
    last = list_entries(db, limit=2, before_id=second.next_before_id)

    assert [e.id for e in first.entries] == [ids[4], ids[3]]
    assert [e.id for e in second.entries] == [ids[2], ids[1]]
    assert [e.id for e in last.entries] == [ids[0]]
    assert last.next_before_id is None


def test_a_new_entry_doesnt_shift_the_next_page(db: Session, actor: StaffUser) -> None:
    ids = [add_entry(db, actor).id for _ in range(4)]
    first = list_entries(db, limit=2)

    add_entry(db, actor)

    second = list_entries(db, limit=2, before_id=first.next_before_id)
    assert [e.id for e in second.entries] == [ids[1], ids[0]]


def test_a_full_last_page_says_there_is_no_more(db: Session, actor: StaffUser) -> None:
    for _ in range(2):
        add_entry(db, actor)

    assert list_entries(db, limit=2).next_before_id is None


def test_filter_by_staff_member(db: Session, actor: StaffUser) -> None:
    other = StaffUser(display_name="Noa", role=Role.INSTRUCTOR, pin_hash=FAKE_HASH)
    db.add(other)
    db.flush()
    add_entry(db, actor)
    theirs = add_entry(db, other)

    page = list_entries(db, staff_user_id=other.id)

    assert [e.id for e in page.entries] == [theirs.id]
    assert page.entries[0].staff_name == "Noa"


def test_dates_are_local_days_both_included(db: Session, actor: StaffUser) -> None:
    # Israel is UTC+2 in November (winter time), so each local day starts
    # at 22:00 UTC the day before: 7–8 November runs from 6 November 22:00
    # to 8 November 22:00 UTC.
    too_early = add_entry(db, actor, at=datetime(2026, 11, 6, 21, 59, tzinfo=UTC))
    first_minute = add_entry(db, actor, at=datetime(2026, 11, 6, 22, 0, tzinfo=UTC))
    last_minute = add_entry(db, actor, at=datetime(2026, 11, 8, 21, 59, tzinfo=UTC))
    too_late = add_entry(db, actor, at=datetime(2026, 11, 8, 22, 0, tzinfo=UTC))

    page = list_entries(db, from_date=date(2026, 11, 7), to_date=date(2026, 11, 8))

    assert {e.id for e in page.entries} == {first_minute.id, last_minute.id}
    assert too_early.id not in {e.id for e in page.entries}
    assert too_late.id not in {e.id for e in page.entries}


def test_filter_by_target(db: Session, actor: StaffUser) -> None:
    add_entry(db, actor, target_type="customer", target_id=1)
    wanted = add_entry(db, actor, target_type="customer", target_id=2)
    add_entry(db, actor, target_type="price", target_id=2)

    by_type = list_entries(db, target_type="customer")
    by_target = list_entries(db, target_type="customer", target_id=2)

    assert len(by_type.entries) == 2
    assert [e.id for e in by_target.entries] == [wanted.id]


def test_a_target_id_needs_a_target_type(db: Session) -> None:
    with pytest.raises(ValueError, match="target_type"):
        list_entries(db, target_id=3)


def test_staff_and_customer_targets_carry_their_names(
    db: Session, actor: StaffUser
) -> None:
    customer = Customer(
        first_name="Yael",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1990, 1, 1),
    )
    db.add(customer)
    db.flush()
    add_entry(db, actor, target_type="customer", target_id=customer.id)
    add_entry(db, actor, target_type="staff_user", target_id=actor.id)
    add_entry(db, actor, target_type="price", target_id=1)
    # A target that no longer resolves (or never did) has no name.
    add_entry(db, actor, target_type="customer", target_id=999)

    names = [e.target_name for e in list_entries(db).entries]

    assert names == [None, None, "Dana", "Yael Levi"]


def test_older_shapes_and_unknown_actions_come_back_as_written(
    db: Session, actor: StaffUser
) -> None:
    # A price row from before one price per plan (decision 0036), and an
    # action this version of the code no longer has.
    add_entry(
        db,
        actor,
        action="price.add",
        target_type="price",
        target_id=1,
        after_json='{"age_group": "under_18", "amount_agorot": 15000, "plan": "monthly"}',
    )
    add_entry(db, actor, action="plan.freeze", target_type="plan_choice", target_id=1)
    add_entry(db, actor, after_json="[1, 2]")

    odd_json, unknown, old_price = list_entries(db).entries

    assert old_price.after == {
        "age_group": "under_18",
        "amount_agorot": 15000,
        "plan": "monthly",
    }
    assert unknown.action == "plan.freeze"
    assert odd_json.after == {"value": [1, 2]}
