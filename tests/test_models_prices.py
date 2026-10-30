"""The prices table model: defaults, and the checks the database itself
enforces. Amounts are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import AgeGroup, Plan, Price
from app.core.months import Month


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def insert(db: Session, **values: object) -> None:
    """Insert a row with plain SQL, past the model's own types, the way a
    hand edit or a buggy query would."""
    row = {
        "plan": "monthly",
        "age_group": "adult",
        "amount_agorot": 10000,
        "valid_from_month": "2026-11",
        "created_at": "2026-10-30 09:00:00.000000",
        **values,
    }
    db.execute(
        text(
            "INSERT INTO prices (plan, age_group, amount_agorot, valid_from_month,"
            " created_at) VALUES (:plan, :age_group, :amount_agorot,"
            " :valid_from_month, :created_at)"
        ),
        row,
    )
    db.flush()


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(
        Price(
            plan=Plan.TRI_MONTHLY,
            age_group=AgeGroup.UNDER_18,
            amount_agorot=10000,
            valid_from_month=Month(2026, 11),
        )
    )
    db.commit()
    db.expire_all()

    row = db.query(Price).one()
    assert row.plan is Plan.TRI_MONTHLY
    assert row.age_group is AgeGroup.UNDER_18
    assert row.valid_from_month == Month(2026, 11)
    assert row.created_at.tzinfo is not None


def test_the_same_price_and_month_can_have_several_rows(db: Session) -> None:
    # A correction is a new row, so this can't be unique.
    insert(db)
    insert(db, amount_agorot=12000)
    assert db.query(Price).count() == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"plan": "weekly"},
        {"age_group": "senior"},
        {"amount_agorot": -1},
        {"amount_agorot": 100.5},
        {"amount_agorot": "a lot"},
        {"valid_from_month": "2026-13"},
        {"valid_from_month": "2026-00"},
        {"valid_from_month": "2026-3"},
        {"valid_from_month": "2026-11-01"},
        {"valid_from_month": "soon"},
        {"valid_from_month": ""},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **bad)


@pytest.mark.parametrize(
    "missing", ["plan", "age_group", "amount_agorot", "valid_from_month"]
)
def test_every_field_is_required(db: Session, missing: str) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **{missing: None})


def test_free_is_allowed_by_the_database(db: Session) -> None:
    insert(db, amount_agorot=0)
    assert db.query(Price).one().amount_agorot == 0
