"""Customers: phone normalising, adding (and reactivating by phone),
editing, the date of birth, deactivating, and their activity-log entries.
Names and phone numbers are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import customers
from app.core.customers import (
    CustomerField,
    CustomerInactiveError,
    InvalidCustomerError,
    InvalidPhoneError,
    PhoneTakenError,
    add_customer,
    change_date_of_birth,
    deactivate_customer,
    edit_customer,
    find_by_phone,
    list_customers,
    normalise_phone,
    reactivate_customer,
)
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, Customer, StaffUser
from app.core.permissions import Role

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# 14:00 in Israel, so "today" is the same date in UTC and locally.
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
NOA = {
    "first_name": "Noa",
    "last_name": "Levi",
    "phone": "050-123 4567",
    "date_of_birth": date(2001, 5, 17),
}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(customers, "utc_now", lambda: NOW)


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def staff(db: Session) -> StaffUser:
    member = StaffUser(
        display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH
    )
    db.add(member)
    db.flush()
    return member


@pytest.fixture
def noa(db: Session, staff: StaffUser) -> Customer:
    return add_customer(db, **NOA, by=staff).customer


def log(db: Session) -> list[tuple]:
    """Every log entry as (action, target id, before, after)."""
    entries = db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id))
    return [
        (
            entry.action,
            entry.target_id,
            entry.before_json and json.loads(entry.before_json),
            entry.after_json and json.loads(entry.after_json),
        )
        for entry in entries
    ]


# ── Phone numbers ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "typed",
    [
        "0501234567",
        "050-1234567",
        "050-123-4567",
        " 050 123 4567 ",
        "(050) 123.4567",
        "+972501234567",
        "+972 50-123-4567",
        "+972 050 123 4567",
        "972501234567",
        "00972501234567",
        "‎050-1234567‏",  # direction marks from pasted Hebrew text
        "０５０１２３４５６７",  # full-width digits
    ],
)
def test_every_way_of_typing_a_mobile_is_the_same_number(typed: str) -> None:
    assert normalise_phone(typed) == "+972501234567"


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("03-1234567", "+97231234567"),
        ("02 123 4567", "+97221234567"),
        ("+972-4-1234567", "+97241234567"),
        ("077-1234567", "+972771234567"),
    ],
)
def test_landlines_and_07x_numbers(typed: str, stored: str) -> None:
    assert normalise_phone(typed) == stored


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "050123456",  # a digit short
        "05012345678",  # a digit too many
        "031234567 8",
        "0312345",
        "501234567",  # no leading 0 or country code
        "+1 212 555 0100",
        "+97250123456",
        "050-12a4567",
        "050_1234567",
        "1-800-123-456",
        "061234567",
        "0",
        "+972",
        "+9720",
        "050+1234567",
        "٠٥٠١٢٣٤٥٦٧",  # Arabic-Indic digits aren't converted
    ],
)
def test_anything_else_is_refused(typed: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalise_phone(typed)


def test_find_by_phone_takes_any_typed_form(db: Session, noa: Customer) -> None:
    assert find_by_phone(db, "+972 50 123 4567") is noa
    assert find_by_phone(db, "0521234567") is None
    assert find_by_phone(db, "not a phone") is None


# ── Adding ──────────────────────────────────────────────────────────────


def test_adding_stores_the_cleaned_values_and_logs_them(
    db: Session, staff: StaffUser
) -> None:
    added = add_customer(
        db,
        first_name="  Noa ",
        last_name="Ben   David",
        phone="050-123 4567",
        date_of_birth=date(2001, 5, 17),
        notes=" knee injury, no squats \r\n",
        by=staff,
    )

    customer = added.customer
    assert not added.reactivated
    assert customer.id is not None
    assert (customer.first_name, customer.last_name) == ("Noa", "Ben David")
    assert customer.phone == "+972501234567"
    assert customer.notes == "knee injury, no squats"
    assert customer.active
    assert log(db) == [
        (
            "customer.create",
            customer.id,
            None,
            {
                "first_name": "Noa",
                "last_name": "Ben David",
                "phone": "+972501234567",
                "date_of_birth": "2001-05-17",
                "notes": "knee injury, no squats",
                "active": True,
            },
        )
    ]


def test_hebrew_names_are_fine(db: Session, staff: StaffUser) -> None:
    added = add_customer(
        db, **{**NOA, "first_name": "נועה", "last_name": "לוי"}, by=staff
    )
    assert added.customer.first_name == "נועה"


def test_every_invalid_field_is_named_at_once(db: Session, staff: StaffUser) -> None:
    with pytest.raises(InvalidCustomerError) as refused:
        add_customer(
            db,
            first_name=" ",
            last_name="x" * 51,
            phone="12345",
            date_of_birth=date(2027, 1, 1),
            notes="x" * 257,
            by=staff,
        )

    assert refused.value.fields == set(CustomerField)
    assert db.scalars(select(Customer)).all() == []
    assert log(db) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_name", "No​a"),  # zero-width space
        ("last_name", "Le\x00vi"),
        ("notes", "tab\there"),
        ("date_of_birth", datetime(2001, 5, 17, tzinfo=UTC)),
        ("date_of_birth", "2001-05-17"),
        ("date_of_birth", date(1905, 12, 31)),  # more than 120 years ago
        ("date_of_birth", date(2026, 10, 30)),  # tomorrow
    ],
    ids=str,
)
def test_one_invalid_field(
    db: Session, staff: StaffUser, field: str, value: object
) -> None:
    with pytest.raises(InvalidCustomerError) as refused:
        add_customer(db, **{**NOA, field: value}, by=staff)
    assert refused.value.fields == {CustomerField(field)}


def test_born_today_and_120_years_ago_are_accepted(
    db: Session, staff: StaffUser
) -> None:
    add_customer(db, **{**NOA, "date_of_birth": date(2026, 10, 29)}, by=staff)
    add_customer(
        db,
        **{**NOA, "phone": "0521234567", "date_of_birth": date(1906, 1, 1)},
        by=staff,
    )


def test_notes_keep_their_line_breaks(db: Session, staff: StaffUser) -> None:
    added = add_customer(db, **NOA, notes="line one\r\nline two", by=staff)
    assert added.customer.notes == "line one\nline two"


def test_an_active_customers_phone_is_taken(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    with pytest.raises(PhoneTakenError) as refused:
        add_customer(
            db, **{**NOA, "first_name": "Dana", "phone": "+972501234567"}, by=staff
        )

    assert refused.value.customer is noa
    assert len(db.scalars(select(Customer)).all()) == 1


def test_adding_an_inactive_customers_phone_brings_them_back(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    deactivate_customer(db, noa, by=staff)

    added = add_customer(
        db, **{**NOA, "first_name": "Noah", "phone": "972501234567"}, by=staff
    )

    assert added.reactivated
    assert added.customer is noa
    assert noa.active
    # The same person, unchanged: the form's details aren't applied.
    assert noa.first_name == "Noa"
    assert len(db.scalars(select(Customer)).all()) == 1
    assert [entry[0] for entry in log(db)] == [
        "customer.create",
        "customer.deactivate",
        "customer.reactivate",
    ]


def test_an_invalid_form_doesnt_reactivate_anyone(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    deactivate_customer(db, noa, by=staff)

    with pytest.raises(InvalidCustomerError):
        add_customer(db, **{**NOA, "first_name": ""}, by=staff)

    assert not noa.active


# ── Editing ─────────────────────────────────────────────────────────────


def test_editing_logs_only_what_changed(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    edit_customer(
        db,
        noa,
        first_name="Noa",
        last_name="Cohen",
        phone="+972 52 765 4321",
        notes="",
        by=staff,
    )

    assert (noa.last_name, noa.phone) == ("Cohen", "+972527654321")
    assert log(db)[-1] == (
        "customer.edit",
        noa.id,
        {"last_name": "Levi", "phone": "+972501234567"},
        {"last_name": "Cohen", "phone": "+972527654321"},
    )


def test_an_edit_that_changes_nothing_writes_no_entry(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    edit_customer(db, noa, first_name=" Noa ", phone="050-1234567", by=staff)
    edit_customer(db, noa, by=staff)

    assert [entry[0] for entry in log(db)] == ["customer.create"]


def test_editing_to_another_customers_phone_is_refused_even_if_inactive(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    dana = add_customer(
        db, **{**NOA, "first_name": "Dana", "phone": "0527654321"}, by=staff
    ).customer
    deactivate_customer(db, dana, by=staff)

    with pytest.raises(PhoneTakenError) as refused:
        edit_customer(db, noa, phone="052-765-4321", by=staff)

    assert refused.value.customer is dana
    assert noa.phone == "+972501234567"


def test_invalid_edits_change_nothing(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    with pytest.raises(InvalidCustomerError) as refused:
        edit_customer(db, noa, first_name="Dana", phone="nope", by=staff)

    assert refused.value.fields == {CustomerField.PHONE}
    assert noa.first_name == "Noa"


def test_an_inactive_customer_cant_be_edited(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    deactivate_customer(db, noa, by=staff)

    with pytest.raises(CustomerInactiveError):
        edit_customer(db, noa, notes="hello", by=staff)
    with pytest.raises(CustomerInactiveError):
        change_date_of_birth(db, noa, date(2002, 1, 1), by=staff)


# ── Date of birth ───────────────────────────────────────────────────────


def test_changing_the_date_of_birth(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    change_date_of_birth(db, noa, date(2010, 3, 4), by=staff)
    change_date_of_birth(db, noa, date(2010, 3, 4), by=staff)

    assert noa.date_of_birth == date(2010, 3, 4)
    assert log(db)[1:] == [
        (
            "customer.change_date_of_birth",
            noa.id,
            {"date_of_birth": "2001-05-17"},
            {"date_of_birth": "2010-03-04"},
        )
    ]


def test_an_impossible_date_of_birth_is_refused(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    with pytest.raises(InvalidCustomerError):
        change_date_of_birth(db, noa, date(2027, 1, 1), by=staff)
    assert noa.date_of_birth == date(2001, 5, 17)


# ── Deactivating and the list ───────────────────────────────────────────


def test_deactivating_and_reactivating(
    db: Session, staff: StaffUser, noa: Customer
) -> None:
    deactivate_customer(db, noa, by=staff)
    deactivate_customer(db, noa, by=staff)
    reactivate_customer(db, noa, by=staff)
    reactivate_customer(db, noa, by=staff)

    assert noa.active
    assert log(db)[1:] == [
        ("customer.deactivate", noa.id, {"active": True}, {"active": False}),
        ("customer.reactivate", noa.id, {"active": False}, {"active": True}),
    ]


def test_the_list_shows_active_or_inactive_customers_by_name(
    db: Session, staff: StaffUser
) -> None:
    def add(first: str, last: str, phone: str) -> Customer:
        return add_customer(
            db,
            first_name=first,
            last_name=last,
            phone=phone,
            date_of_birth=date(2000, 1, 1),
            by=staff,
        ).customer

    yael = add("Yael", "Mizrahi", "0501111111")
    dana_l = add("Dana", "Levi", "0502222222")
    dana_c = add("Dana", "Cohen", "0503333333")
    gone = add("Avi", "Peretz", "0504444444")
    deactivate_customer(db, gone, by=staff)

    assert list_customers(db) == [dana_c, dana_l, yael]
    assert list_customers(db, active=False) == [gone]
