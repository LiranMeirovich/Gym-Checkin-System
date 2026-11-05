"""The checkins table model: types, the checks the database itself
enforces, that rows can't be changed or deleted, and that a phone
check-in uses its own customer's phone. Names and numbers are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import CheckIn, CheckInMethod

# Not real hashes; they only have to look like ones to pass the CHECKs.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
FAKE_TOKEN_HASH = "a" * 64
OTHER_TOKEN_HASH = "b" * 64


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
                " failed_attempts, active, created_at) VALUES ('Noa', 'instructor',"
                " :hash, 0, 1, '2026-10-30 09:00:00.000000')"
            ),
            {"hash": FAKE_PIN_HASH},
        )
        # Device 1 is customer 1's phone, device 2 customer 2's.
        for customer_id, token_hash in ((1, FAKE_TOKEN_HASH), (2, OTHER_TOKEN_HASH)):
            db_session.execute(
                text(
                    "INSERT INTO device_sessions (customer_id, token_hash,"
                    " user_agent, created_at, last_seen_at) VALUES (:customer_id,"
                    " :token_hash, '', '2026-11-01 09:00:00.000000',"
                    " '2026-11-01 09:00:00.000000')"
                ),
                {"customer_id": customer_id, "token_hash": token_hash},
            )
        db_session.commit()
        yield db_session


def insert(db: Session, **values: object) -> int:
    """Insert a row with plain SQL, past the model's own types, the way a
    hand edit or a buggy query would. Returns its id. A phone check-in by
    customer 1 by default."""
    row = {
        "customer_id": 1,
        "checked_in_at": "2026-11-05 09:00:00.000000",
        "method": "phone",
        "device_session_id": 1,
        "staff_user_id": None,
        **values,
    }
    result = db.execute(
        text(
            "INSERT INTO checkins (customer_id, checked_in_at, method,"
            " device_session_id, staff_user_id) VALUES (:customer_id,"
            " :checked_in_at, :method, :device_session_id, :staff_user_id)"
            " RETURNING id"
        ),
        row,
    )
    return result.scalar_one()


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(CheckIn(customer_id=1, method=CheckInMethod.PHONE, device_session_id=1))
    db.commit()
    db.expire_all()

    row = db.query(CheckIn).one()
    assert row.method is CheckInMethod.PHONE
    assert row.device is not None and row.device.id == 1
    assert row.staff is None
    assert row.checked_in_at.tzinfo is not None


@pytest.mark.parametrize(
    "good",
    [
        {},
        {"method": "manual", "device_session_id": None, "staff_user_id": 1},
        {"customer_id": 2, "device_session_id": 2},
    ],
)
def test_the_database_accepts_good_rows(db: Session, good: dict[str, object]) -> None:
    insert(db, **good)
    db.commit()


@pytest.mark.parametrize(
    "bad",
    [
        # A phone check-in without its phone, or naming a staff member.
        {"device_session_id": None},
        {"staff_user_id": 1},
        # A manual one without its staff member, or naming a phone.
        {"method": "manual"},
        {"method": "manual", "device_session_id": None},
        {"method": "manual", "staff_user_id": 1},
        {"method": "qr", "device_session_id": None},
        {"customer_id": None},
        {"checked_in_at": None},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **bad)


def test_a_phone_check_in_uses_the_same_customers_phone(db: Session) -> None:
    with pytest.raises(IntegrityError, match="same customer's phone"):
        insert(db, customer_id=1, device_session_id=2)


def test_rows_cannot_be_updated_or_deleted(db: Session) -> None:
    row_id = insert(db)
    db.commit()

    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(
            text("UPDATE checkins SET checked_in_at = :at WHERE id = :id"),
            {"at": "2026-11-04 09:00:00.000000", "id": row_id},
        )
    db.rollback()
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text("DELETE FROM checkins WHERE id = :id"), {"id": row_id})
    db.rollback()
    assert db.query(CheckIn).count() == 1


def test_the_triggers_exist_at_head(db: Session) -> None:
    triggers = db.scalars(
        text(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'checkins'"
        )
    ).all()
    assert sorted(triggers) == [
        "checkins_no_delete",
        "checkins_no_update",
        "checkins_same_customer_device",
    ]
