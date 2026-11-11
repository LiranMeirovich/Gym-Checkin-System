"""The punch_cards table model, and check-ins charged to a card: types, the
checks the database itself enforces, that cards can't be changed or
deleted, and the two check-in triggers (same customer, at most
``CARD_ENTRIES``). Names and amounts are made up."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import CARD_ENTRIES, CheckIn, ChosenBy, PunchCard
from app.core.months import Month

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as db_session:
        for phone in ("+972501234567", "+972507654321"):
            db_session.execute(
                text(
                    "INSERT INTO customers (first_name, last_name, phone,"
                    " date_of_birth, notes, created_at, active) VALUES"
                    " ('Dana', 'Levi', :phone, '1990-05-01', '',"
                    " '2026-10-30 09:00:00.000000', 1)"
                ),
                {"phone": phone},
            )
        db_session.execute(
            text(
                "INSERT INTO staff_users (display_name, role, pin_hash,"
                " failed_attempts, active, created_at) VALUES ('Noa', 'manager',"
                " :hash, 0, 1, '2026-10-30 09:00:00.000000')"
            ),
            {"hash": FAKE_PIN_HASH},
        )
        db_session.commit()
        yield db_session


def insert_card(db: Session, **values: object) -> int:
    """Insert a card with plain SQL, past the model's own types. Customer
    1's, bought by them in November 2026, by default. Returns its id."""
    row = {
        "customer_id": 1,
        "price_agorot": 50000,
        "bought_month": "2026-11",
        "expires_on": "2027-01-01",
        "bought_at": "2026-11-05 09:00:00.000000",
        "bought_by": "customer",
        "staff_user_id": None,
        **values,
    }
    return db.execute(
        text(
            "INSERT INTO punch_cards (customer_id, price_agorot, bought_month,"
            " expires_on, bought_at, bought_by, staff_user_id) VALUES"
            " (:customer_id, :price_agorot, :bought_month, :expires_on,"
            " :bought_at, :bought_by, :staff_user_id) RETURNING id"
        ),
        row,
    ).scalar_one()


def insert_checkin(db: Session, card_id: int | None, customer_id: int = 1) -> None:
    """A manual check-in by staff member 1, charged to ``card_id``."""
    db.execute(
        text(
            "INSERT INTO checkins (customer_id, checked_in_at, method,"
            " staff_user_id, punch_card_id) VALUES (:customer_id,"
            " '2026-11-05 09:00:00.000000', 'manual', 1, :card_id)"
        ),
        {"customer_id": customer_id, "card_id": card_id},
    )


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(
        PunchCard(
            customer_id=1,
            price_agorot=50000,
            bought_month=Month(2026, 11),
            expires_on=date(2027, 1, 1),
            bought_by=ChosenBy.STAFF,
            staff_user_id=1,
        )
    )
    db.commit()
    db.expire_all()

    row = db.query(PunchCard).one()
    assert row.bought_month == Month(2026, 11)
    assert row.expires_on == date(2027, 1, 1)
    assert row.bought_by is ChosenBy.STAFF
    assert row.staff is not None and row.staff.id == 1
    assert row.bought_at.tzinfo is not None


@pytest.mark.parametrize(
    "good",
    [
        {},
        {"bought_by": "staff", "staff_user_id": 1},
        {"price_agorot": 0},
        # December's card runs to the end of January.
        {"bought_month": "2026-12", "expires_on": "2027-02-01"},
    ],
)
def test_the_database_accepts_good_rows(db: Session, good: dict[str, object]) -> None:
    insert_card(db, **good)
    db.commit()


@pytest.mark.parametrize(
    "bad",
    [
        # Expiry is the 1st of the month after next, nothing else.
        {"expires_on": "2026-12-31"},
        {"expires_on": "2027-01-02"},
        {"expires_on": "2026-12-01"},
        {"expires_on": None},
        {"bought_month": "2026-13"},
        {"bought_month": "2026-11-01"},
        {"price_agorot": -1},
        {"price_agorot": 100.5},
        # Who bought it and the staff member named must agree.
        {"bought_by": "staff"},
        {"staff_user_id": 1},
        {"bought_by": "desk"},
        {"customer_id": 99},
        {"customer_id": None},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert_card(db, **bad)


def test_cards_cannot_be_updated_or_deleted(db: Session) -> None:
    card_id = insert_card(db)
    db.commit()

    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(
            text("UPDATE punch_cards SET price_agorot = 0 WHERE id = :id"),
            {"id": card_id},
        )
    db.rollback()
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text("DELETE FROM punch_cards WHERE id = :id"), {"id": card_id})
    db.rollback()
    assert db.query(PunchCard).count() == 1


def test_a_card_has_at_most_its_entries(db: Session) -> None:
    card_id = insert_card(db)
    for _ in range(CARD_ENTRIES):
        insert_checkin(db, card_id)
    db.commit()

    with pytest.raises(IntegrityError, match="20 entries"):
        insert_checkin(db, card_id)
    db.rollback()
    # Check-ins not charged to the card are unaffected.
    insert_checkin(db, None)
    db.commit()
    assert db.query(CheckIn).filter_by(punch_card_id=card_id).count() == CARD_ENTRIES


def test_the_entries_trigger_counts_per_card(db: Session) -> None:
    full = insert_card(db)
    for _ in range(CARD_ENTRIES):
        insert_checkin(db, full)
    other = insert_card(db, customer_id=2)
    insert_checkin(db, other, customer_id=2)
    db.commit()


def test_a_check_in_uses_the_same_customers_card(db: Session) -> None:
    card_id = insert_card(db)
    with pytest.raises(IntegrityError, match="same customer's punch card"):
        insert_checkin(db, card_id, customer_id=2)


def test_a_check_in_names_a_real_card(db: Session) -> None:
    with pytest.raises(IntegrityError):
        insert_checkin(db, 99)


def test_the_triggers_exist_at_head(db: Session) -> None:
    triggers = db.scalars(
        text(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'punch_cards'"
        )
    ).all()
    assert sorted(triggers) == ["punch_cards_no_delete", "punch_cards_no_update"]
