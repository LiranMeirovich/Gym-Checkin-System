"""The lists the dashboard shows, each read from its own area: today's
check-ins, health forms waiting for a doctor's note, forms expiring soon and
the newest customers. Names and numbers are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.checkins import checkins_on
from app.core.customers import latest_customers
from app.core.db import get_engine
from app.core.health_forms import forms_expiring, forms_needing_doctor_note
from app.core.models import (
    CheckIn,
    CheckInMethod,
    Customer,
    DeviceSession,
    DoctorNote,
    HealthForm,
    HealthFormAcceptance,
    ImageType,
    StaffUser,
)
from app.core.permissions import Role

# 15 November 2026 in Israel (UTC+2 in November): it starts at 22:00 UTC
# on the 14th and ends at 22:00 UTC on the 15th.
TODAY = date(2026, 11, 15)
DAY_START = datetime(2026, 11, 14, 22, 0, tzinfo=UTC)
DAY_END = datetime(2026, 11, 15, 22, 0, tzinfo=UTC)
FAKE_PDF = b"%PDF-1.4 made up"
FAKE_JPEG = b"\xff\xd8\xff made up"
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


_numbers = iter(range(1_000_000))


def add_customer(
    db: Session,
    first_name: str = "Noa",
    *,
    active: bool = True,
    created_at: datetime = DAY_START,
) -> Customer:
    customer = Customer(
        first_name=first_name,
        last_name="Levi",
        phone=f"+97250{next(_numbers):07d}",
        date_of_birth=date(1990, 5, 1),
        active=active,
        created_at=created_at,
    )
    db.add(customer)
    db.flush()
    return customer


def add_form(
    db: Session,
    customer: Customer,
    *,
    signed_on: date = date(2026, 3, 1),
    expires_on: date | None = None,
    needs_doctor_note: bool = False,
) -> HealthForm:
    form = HealthForm(
        customer_id=customer.id,
        form_version="test",
        answers_json="{}",
        needs_doctor_note=needs_doctor_note,
        signer_name="Noa Levi",
        signed_by_guardian=False,
        signed_on=signed_on,
        expires_on=expires_on or signed_on.replace(year=signed_on.year + 1),
        document=FAKE_PDF,
    )
    db.add(form)
    db.flush()
    return form


def add_note(db: Session, form: HealthForm, staff: StaffUser) -> None:
    db.add(
        DoctorNote(
            health_form_id=form.id,
            image=FAKE_JPEG,
            content_type=ImageType.JPEG,
            staff_user_id=staff.id,
        )
    )
    db.flush()


def add_staff(db: Session) -> StaffUser:
    staff = StaffUser(display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH)
    db.add(staff)
    db.flush()
    return staff


def add_phone(db: Session, customer: Customer) -> DeviceSession:
    device = DeviceSession(
        customer_id=customer.id,
        token_hash=f"{next(_numbers):064d}",
        created_at=DAY_START - timedelta(days=30),
        last_seen_at=DAY_START - timedelta(days=30),
    )
    db.add(device)
    db.flush()
    return device


def check_in(
    db: Session, customer: Customer, at: datetime, staff: StaffUser | None = None
) -> CheckIn:
    entry = CheckIn(
        customer_id=customer.id,
        checked_in_at=at,
        method=CheckInMethod.MANUAL if staff else CheckInMethod.PHONE,
        staff_user_id=staff.id if staff else None,
        device_session_id=None if staff else add_phone(db, customer).id,
    )
    db.add(entry)
    db.flush()
    return entry


def names(rows: list) -> list[str]:
    return [row.customer.first_name for row in rows]


# ── Today's check-ins ───────────────────────────────────────────────────


def test_todays_check_ins_are_everyones_newest_first(db: Session) -> None:
    staff = add_staff(db)
    noa, dan = add_customer(db, "Noa"), add_customer(db, "Dan")
    check_in(db, noa, DAY_START + timedelta(hours=8))
    check_in(db, dan, DAY_START + timedelta(hours=10), staff)
    check_in(db, noa, DAY_START + timedelta(hours=12))

    rows = checkins_on(db, TODAY)

    assert names(rows) == ["Noa", "Dan", "Noa"]
    assert [row.method for row in rows] == [
        CheckInMethod.PHONE,
        CheckInMethod.MANUAL,
        CheckInMethod.PHONE,
    ]


def test_the_day_is_israels_from_midnight_to_midnight(db: Session) -> None:
    noa = add_customer(db)
    second = timedelta(seconds=1)
    before = check_in(db, noa, DAY_START - second)
    first = check_in(db, noa, DAY_START)
    last = check_in(db, noa, DAY_END - second)
    after = check_in(db, noa, DAY_END)

    ids = [row.id for row in checkins_on(db, TODAY)]

    assert ids == [last.id, first.id]
    assert before.id not in ids and after.id not in ids


def test_a_day_without_check_ins_is_empty(db: Session) -> None:
    check_in(db, add_customer(db), DAY_START - timedelta(days=1))

    assert checkins_on(db, TODAY) == []


# ── Waiting for a doctor's note ─────────────────────────────────────────


def test_a_yes_answer_without_a_note_is_listed(db: Session) -> None:
    noa = add_customer(db)
    form = add_form(db, noa, needs_doctor_note=True)

    rows = forms_needing_doctor_note(db, TODAY)

    assert [(row.customer.id, row.form.id) for row in rows] == [(noa.id, form.id)]


def test_a_note_takes_the_form_off_the_list(db: Session) -> None:
    form = add_form(db, add_customer(db), needs_doctor_note=True)
    add_note(db, form, add_staff(db))

    assert forms_needing_doctor_note(db, TODAY) == []


def test_the_managers_acceptance_takes_the_form_off_the_list(db: Session) -> None:
    form = add_form(db, add_customer(db), needs_doctor_note=True)
    db.add(HealthFormAcceptance(health_form_id=form.id, staff_user_id=add_staff(db).id))
    db.flush()

    assert forms_needing_doctor_note(db, TODAY) == []


def test_forms_that_dont_count_today_arent_waiting(db: Session) -> None:
    # No "yes" at all.
    add_form(db, add_customer(db, "Clean"))
    # A "yes" that has expired: the customer needs a new form, not a note.
    add_form(
        db,
        add_customer(db, "Expired"),
        signed_on=date(2025, 11, 1),
        expires_on=TODAY - timedelta(days=1),
        needs_doctor_note=True,
    )
    # An old "yes" replaced by a newer form without one.
    replaced = add_customer(db, "Replaced")
    add_form(db, replaced, signed_on=date(2026, 1, 1), needs_doctor_note=True)
    add_form(db, replaced, signed_on=date(2026, 6, 1))
    # A deactivated customer.
    add_form(db, add_customer(db, "Gone", active=False), needs_doctor_note=True)

    assert forms_needing_doctor_note(db, TODAY) == []


def test_the_longest_wait_comes_first(db: Session) -> None:
    add_form(
        db,
        add_customer(db, "Recent"),
        signed_on=date(2026, 11, 10),
        needs_doctor_note=True,
    )
    add_form(
        db,
        add_customer(db, "Waiting"),
        signed_on=date(2026, 9, 1),
        needs_doctor_note=True,
    )

    assert names(forms_needing_doctor_note(db, TODAY)) == ["Waiting", "Recent"]


# ── Expiring soon ───────────────────────────────────────────────────────


def expiring_on(db: Session, name: str, last_day: date, **form: object) -> HealthForm:
    return add_form(
        db,
        add_customer(db, name),
        signed_on=date(2025, 12, 1),
        expires_on=last_day,
        **form,
    )


def test_forms_ending_within_30_days_are_listed_soonest_first(db: Session) -> None:
    expiring_on(db, "Day30", TODAY + timedelta(days=30))
    expiring_on(db, "Today", TODAY)
    expiring_on(db, "Day31", TODAY + timedelta(days=31))
    expiring_on(db, "Yesterday", TODAY - timedelta(days=1))

    rows = forms_expiring(db, TODAY)

    assert names(rows) == ["Today", "Day30"]
    assert rows[0].form.expires_on == TODAY


def test_a_newer_form_takes_the_customer_off_the_list(db: Session) -> None:
    noa = add_customer(db)
    add_form(
        db, noa, signed_on=date(2025, 11, 20), expires_on=TODAY + timedelta(days=4)
    )
    add_form(db, noa, signed_on=date(2026, 11, 14))

    assert forms_expiring(db, TODAY) == []


def test_a_yes_form_is_expiring_only_once_it_has_its_note(db: Session) -> None:
    expiring_on(db, "Waiting", TODAY + timedelta(days=5), needs_doctor_note=True)
    noted = expiring_on(db, "Noted", TODAY + timedelta(days=6), needs_doctor_note=True)
    add_note(db, noted, add_staff(db))

    assert names(forms_expiring(db, TODAY)) == ["Noted"]
    assert names(forms_needing_doctor_note(db, TODAY)) == ["Waiting"]


def test_a_deactivated_customers_form_isnt_expiring(db: Session) -> None:
    add_form(
        db,
        add_customer(db, active=False),
        signed_on=date(2025, 12, 1),
        expires_on=TODAY + timedelta(days=3),
    )

    assert forms_expiring(db, TODAY) == []


# ── Newest customers ────────────────────────────────────────────────────


def test_the_newest_active_customers_come_first(db: Session) -> None:
    add_customer(db, "Old", created_at=DAY_START - timedelta(days=9))
    add_customer(db, "New", created_at=DAY_START)
    add_customer(db, "Gone", active=False, created_at=DAY_START + timedelta(hours=1))
    add_customer(db, "Middle", created_at=DAY_START - timedelta(days=2))

    assert [c.first_name for c in latest_customers(db)] == ["New", "Middle", "Old"]


def test_only_the_ten_newest_are_listed(db: Session) -> None:
    for day in range(12):
        add_customer(db, f"C{day}", created_at=DAY_START - timedelta(days=day))

    newest = latest_customers(db)

    assert [c.first_name for c in newest] == [f"C{day}" for day in range(10)]


def test_a_limit_below_one_is_refused(db: Session) -> None:
    with pytest.raises(ValueError):
        latest_customers(db, limit=0)
