"""The reports table model: types, the checks the database itself enforces,
and that a generation can't be changed or deleted. Names are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Report
from app.core.months import Month

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as db_session:
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


def insert_report(db: Session, **values: object) -> int:
    """Insert a generation with plain SQL, past the model's own types.
    November 2026's, by staff member 1, with no rows, by default."""
    row = {
        "month": "2026-11",
        "generated_at": "2026-12-01 09:00:00.000000",
        "staff_user_id": 1,
        "rows_json": "[]",
        **values,
    }
    return db.execute(
        text(
            "INSERT INTO reports (month, generated_at, staff_user_id, rows_json)"
            " VALUES (:month, :generated_at, :staff_user_id, :rows_json)"
            " RETURNING id"
        ),
        row,
    ).scalar_one()


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(Report(month=Month(2026, 11), staff_user_id=1, rows_json="[]"))
    db.commit()
    db.expire_all()

    row = db.query(Report).one()
    assert row.month == Month(2026, 11)
    assert row.staff is not None and row.staff.id == 1
    assert row.generated_at.tzinfo is not None


@pytest.mark.parametrize(
    "good",
    [
        {},
        # The scheduled job names no staff member.
        {"staff_user_id": None},
        {"rows_json": '[{"customer_id": 1}]'},
    ],
)
def test_the_database_accepts_good_rows(db: Session, good: dict[str, object]) -> None:
    insert_report(db, **good)
    db.commit()


@pytest.mark.parametrize(
    "bad",
    [
        {"month": "2026-13"},
        {"month": "2026-11-01"},
        {"month": None},
        {"rows_json": "not json"},
        {"rows_json": None},
        {"staff_user_id": 99},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert_report(db, **bad)


def test_a_month_can_be_generated_again(db: Session) -> None:
    insert_report(db)
    insert_report(db, generated_at="2026-12-02 09:00:00.000000")
    db.commit()

    assert db.query(Report).count() == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE reports SET rows_json = '[]'",
        "DELETE FROM reports",
    ],
)
def test_a_generation_cant_be_changed_or_deleted(db: Session, statement: str) -> None:
    insert_report(db)
    db.commit()

    with pytest.raises(IntegrityError, match="reports is append-only"):
        db.execute(text(statement))
