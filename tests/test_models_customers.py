"""The customers table model: defaults, and the checks the database itself
enforces. Names and phone numbers are made up."""

from collections.abc import Iterator
from datetime import UTC, date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Customer


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def insert(db: Session, **values: object) -> None:
    """Insert a row with plain SQL, past the model's own types, the way a
    hand edit or a buggy query would."""
    row = {
        "first_name": "Noa",
        "last_name": "Levi",
        "phone": "+972501234567",
        "date_of_birth": "2001-05-17",
        "notes": "",
        "created_at": "2026-10-29 09:00:00.000000",
        "active": True,
        **values,
    }
    db.execute(
        text(
            "INSERT INTO customers (first_name, last_name, phone, date_of_birth,"
            " notes, created_at, active) VALUES (:first_name, :last_name, :phone,"
            " :date_of_birth, :notes, :created_at, :active)"
        ),
        row,
    )
    db.flush()


def test_a_new_row_gets_its_defaults(db: Session) -> None:
    db.add(
        Customer(
            first_name="Noa",
            last_name="Levi",
            phone="+972501234567",
            date_of_birth=date(2001, 5, 17),
        )
    )
    db.commit()

    row = db.query(Customer).one()
    assert row.notes == ""
    assert row.active is True
    assert row.date_of_birth == date(2001, 5, 17)
    assert row.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    "phone",
    [
        "+972501234567",  # mobile
        "+97231234567",  # landline
        "+972771234567",  # 07x
    ],
)
def test_normalised_phones_are_accepted(db: Session, phone: str) -> None:
    insert(db, phone=phone)


@pytest.mark.parametrize(
    "values",
    [
        {"first_name": ""},
        {"first_name": "x" * 51},
        {"last_name": ""},
        {"last_name": "x" * 51},
        {"phone": "0501234567"},
        {"phone": "+9720501234567"},
        {"phone": "+97250123456a"},
        {"phone": "+972 50123456"},
        {"phone": "+9725012345678"},
        {"phone": "+9723123456"},
        {"phone": "+1501234567"},
        {"date_of_birth": "17/05/2001"},
        {"date_of_birth": "2001-02-30"},
        {"date_of_birth": "2001-5-17"},
        {"date_of_birth": ""},
        {"notes": "x" * 257},
        {"active": 2},
    ],
    ids=str,
)
def test_the_database_refuses_bad_values(db: Session, values: dict) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **values)


def test_notes_may_be_256_hebrew_characters(db: Session) -> None:
    # length() counts characters, not bytes; Hebrew is 2 bytes each.
    insert(db, notes="א" * 256, first_name="נ" * 50)


def test_two_customers_cannot_share_a_phone(db: Session) -> None:
    insert(db)
    with pytest.raises(IntegrityError):
        insert(db, first_name="Dana")


def test_an_inactive_customers_phone_cannot_be_reused(db: Session) -> None:
    # One phone is one person (decision 0023): adding them again brings the
    # old row back instead.
    insert(db, active=False)
    with pytest.raises(IntegrityError):
        insert(db, first_name="Dana")
