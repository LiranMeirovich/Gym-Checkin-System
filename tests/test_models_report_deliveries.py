"""The report_deliveries table model: types, the checks the database itself
enforces, and that a step can't be changed or deleted. Addresses and names
are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import DeliveryKind, EmailOutcome, ReportDelivery

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
        db_session.execute(
            text(
                "INSERT INTO reports (month, generated_at, rows_json)"
                " VALUES ('2026-10', '2026-11-01 00:05:00.000000', '[]')"
            )
        )
        db_session.commit()
        yield db_session


def insert_step(db: Session, **values: object) -> None:
    """Insert a step with plain SQL, past the model's own types. The
    scheduled job's email to the manager of report 1, by default."""
    row = {
        "report_id": 1,
        "kind": "manager_email",
        "outcome": "sent",
        "recipients_json": '["manager@example.com"]',
        "staff_user_id": None,
        "at": "2026-11-01 00:05:01.000000",
        **values,
    }
    db.execute(
        text(
            "INSERT INTO report_deliveries (report_id, kind, outcome,"
            " recipients_json, staff_user_id, at) VALUES (:report_id, :kind,"
            " :outcome, :recipients_json, :staff_user_id, :at)"
        ),
        row,
    )


APPROVAL = {"kind": "approval", "outcome": None, "recipients_json": None}


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(
        ReportDelivery(
            report_id=1,
            kind=DeliveryKind.RECIPIENTS_EMAIL,
            outcome=EmailOutcome.FAILED,
            recipients_json='["a@example.com"]',
            staff_user_id=1,
        )
    )
    db.commit()
    db.expire_all()

    row = db.query(ReportDelivery).one()
    assert row.kind is DeliveryKind.RECIPIENTS_EMAIL
    assert row.outcome is EmailOutcome.FAILED
    assert row.report.rows_json == "[]"
    assert row.staff is not None and row.staff.id == 1
    assert row.at.tzinfo is not None


@pytest.mark.parametrize(
    "good",
    [
        {},
        {"outcome": "failed"},
        {"kind": "recipients_email", "recipients_json": "[]", "staff_user_id": 1},
        {**APPROVAL, "staff_user_id": 1},
    ],
)
def test_the_database_accepts_good_rows(db: Session, good: dict[str, object]) -> None:
    insert_step(db, **good)
    db.commit()


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "emailed"},
        {"kind": None},
        {"outcome": "bounced"},
        # An email has an outcome and its addresses.
        {"outcome": None},
        {"recipients_json": None},
        {"recipients_json": "not json"},
        {"recipients_json": '"manager@example.com"'},
        # An approval has neither, and always names who.
        {**APPROVAL, "staff_user_id": None},
        {**APPROVAL, "staff_user_id": 1, "outcome": "sent"},
        {**APPROVAL, "staff_user_id": 1, "recipients_json": "[]"},
        {"report_id": 99},
        {"report_id": None},
        {"staff_user_id": 99},
        {"at": None},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert_step(db, **bad)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE report_deliveries SET outcome = 'sent'",
        "DELETE FROM report_deliveries",
    ],
)
def test_a_step_cant_be_changed_or_deleted(db: Session, statement: str) -> None:
    insert_step(db, outcome="failed")
    db.commit()

    with pytest.raises(IntegrityError, match="report_deliveries is append-only"):
        db.execute(text(statement))
