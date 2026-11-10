"""The health_form_acceptances table model: types, one acceptance per
form, and that rows can't be changed or deleted. Names are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import HealthFormAcceptance

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as db_session:
        db_session.execute(
            text(
                "INSERT INTO customers (first_name, last_name, phone,"
                " date_of_birth, notes, created_at, active) VALUES"
                " ('Dana', 'Levi', '+972501234567', '1990-05-01', '',"
                " '2026-10-30 09:00:00.000000', 1)"
            )
        )
        db_session.execute(
            text(
                "INSERT INTO staff_users (display_name, role, pin_hash,"
                " failed_attempts, active, created_at) VALUES ('Noa', 'manager',"
                " :hash, 0, 1, '2026-10-30 09:00:00.000000')"
            ),
            {"hash": FAKE_PIN_HASH},
        )
        for signed_on in ("2026-11-01", "2026-11-02"):
            db_session.execute(
                text(
                    "INSERT INTO health_forms (customer_id, form_version,"
                    " answers_json, needs_doctor_note, signer_name,"
                    " signed_by_guardian, signed_on, expires_on, document,"
                    " created_at) VALUES (1, 'test', '{}', 1, 'Dana Levi', 0,"
                    " :signed_on, '2027-10-31', :pdf, '2026-11-01 09:00:00.000000')"
                ),
                {"signed_on": signed_on, "pdf": b"%PDF-1.4 made up"},
            )
        db_session.commit()
        yield db_session


def insert(db: Session, **values: object) -> int:
    """Insert a row with plain SQL, past the model's own types. Returns its
    id. An acceptance of form 1 by default."""
    row = {
        "health_form_id": 1,
        "staff_user_id": 1,
        "created_at": "2026-11-05 09:00:00.000000",
        **values,
    }
    result = db.execute(
        text(
            "INSERT INTO health_form_acceptances (health_form_id, staff_user_id,"
            " created_at) VALUES (:health_form_id, :staff_user_id, :created_at)"
            " RETURNING id"
        ),
        row,
    )
    return result.scalar_one()


def test_a_row_reads_back_with_its_timestamp(db: Session) -> None:
    db.add(HealthFormAcceptance(health_form_id=1, staff_user_id=1))
    db.commit()
    db.expire_all()

    row = db.query(HealthFormAcceptance).one()
    assert row.health_form.id == 1
    assert row.staff.id == 1
    assert row.created_at.tzinfo is not None


def test_a_form_is_accepted_at_most_once(db: Session) -> None:
    insert(db)
    insert(db, health_form_id=2)

    with pytest.raises(IntegrityError):
        insert(db)


@pytest.mark.parametrize(
    "bad",
    [
        {"health_form_id": None},
        {"health_form_id": 99},
        {"staff_user_id": None},
        {"staff_user_id": 99},
        {"created_at": None},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **bad)


def test_rows_cannot_be_updated_or_deleted(db: Session) -> None:
    row_id = insert(db)
    db.commit()

    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(
            text("UPDATE health_form_acceptances SET staff_user_id = 1 WHERE id = :id"),
            {"id": row_id},
        )
    db.rollback()
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(
            text("DELETE FROM health_form_acceptances WHERE id = :id"), {"id": row_id}
        )
    db.rollback()
    assert db.query(HealthFormAcceptance).count() == 1


def test_the_triggers_exist_at_head(db: Session) -> None:
    triggers = db.scalars(
        text(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'health_form_acceptances'"
        )
    ).all()
    assert sorted(triggers) == [
        "health_form_acceptances_no_delete",
        "health_form_acceptances_no_update",
    ]
