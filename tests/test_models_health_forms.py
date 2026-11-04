"""The health_forms table model: the checks the database itself enforces,
that the PDF is loaded only when asked for, and that rows can't be changed
or deleted. Names and answers are made up."""

from collections.abc import Iterator
from datetime import UTC, date
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Customer, HealthForm
from app.core.models.health_forms import DOCUMENT_MAX_BYTES

PDF = b"%PDF-1.7 made-up snapshot"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        session.add(
            Customer(
                id=1,
                first_name="Noa",
                last_name="Levi",
                phone="+972501234567",
                date_of_birth=date(1990, 5, 1),
            )
        )
        session.commit()
        yield session


def add_form(db: Session, **values: object) -> HealthForm:
    fields: dict[str, object] = {
        "customer_id": 1,
        "form_version": "2026-11",
        "answers_json": '{"chronic_illness": false}',
        "needs_doctor_note": False,
        "signer_name": "Noa Levi",
        "signed_by_guardian": False,
        "signed_on": date(2026, 11, 4),
        "expires_on": date(2027, 11, 3),
        "document": PDF,
    } | values
    form = HealthForm(**fields)
    db.add(form)
    db.commit()
    return form


def test_a_new_row_gets_its_defaults(db: Session) -> None:
    form = add_form(db)

    assert form.created_at.tzinfo is UTC


def test_the_document_loads_only_when_asked_for(db: Session) -> None:
    add_form(db)
    db.expunge_all()

    form = db.scalars(select(HealthForm)).one()

    assert "document" in inspect(form).unloaded
    assert form.document == PDF


@pytest.mark.parametrize(
    "values",
    [
        {"answers_json": "{not json"},
        {"signer_name": ""},
        {"signer_name": "x" * 101},
        {"form_version": ""},
        {"expires_on": date(2026, 11, 4)},
        {"expires_on": date(2026, 11, 3)},
        {"document": b"not a pdf"},
        {"document": b""},
        {"document": b"%PDF-" + b"0" * DOCUMENT_MAX_BYTES},
        {"customer_id": 99},
    ],
    ids=[
        "answers not json",
        "empty signer",
        "long signer",
        "empty version",
        "expires the day it was signed",
        "expires before it was signed",
        "not a pdf",
        "empty document",
        "document too large",
        "unknown customer",
    ],
)
def test_the_database_refuses_a_bad_row(db: Session, values: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        add_form(db, **values)


@pytest.mark.parametrize(
    ("signed_on", "expires_on"),
    [("2026-13-01", "2027-11-03"), ("2026-11-04", "2027-02-30")],
    ids=["signed_on", "expires_on"],
)
def test_the_database_refuses_text_that_isnt_a_date(
    db: Session, signed_on: str, expires_on: str
) -> None:
    # Raw SQL: the ORM would never write anything but a date.
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO health_forms (customer_id, form_version, answers_json,"
                " needs_doctor_note, signer_name, signed_by_guardian, signed_on,"
                " expires_on, document, created_at)"
                " VALUES (1, '2026-11', '{}', 0, 'Noa Levi', 0, :signed_on,"
                " :expires_on, :document, '2026-11-04 10:00:00.000000')"
            ),
            {"signed_on": signed_on, "expires_on": expires_on, "document": PDF},
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE health_forms SET expires_on = '2030-01-01'",
        "DELETE FROM health_forms",
    ],
    ids=["update", "delete"],
)
def test_rows_cant_be_changed_or_deleted(db: Session, statement: str) -> None:
    add_form(db)
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text(statement))
