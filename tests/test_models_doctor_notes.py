"""The doctor_notes table model: types, the image checks the database
itself enforces, and that rows can't be changed or deleted. Names and
images are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import DoctorNote, ImageType
from app.core.models.doctor_notes import IMAGE_MAX_BYTES

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# Only the opening bytes matter to the database.
FAKE_JPEG = b"\xff\xd8\xff\xe0 made up"
FAKE_PNG = b"\x89PNG\r\n\x1a\n made up"


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
                " failed_attempts, active, created_at) VALUES ('Noa', 'instructor',"
                " :hash, 0, 1, '2026-10-30 09:00:00.000000')"
            ),
            {"hash": FAKE_PIN_HASH},
        )
        db_session.execute(
            text(
                "INSERT INTO health_forms (customer_id, form_version, answers_json,"
                " needs_doctor_note, signer_name, signed_by_guardian, signed_on,"
                " expires_on, document, created_at) VALUES (1, 'test', '{}', 1,"
                " 'Dana Levi', 0, '2026-11-01', '2027-10-31', :pdf,"
                " '2026-11-01 09:00:00.000000')"
            ),
            {"pdf": b"%PDF-1.4 made up"},
        )
        db_session.commit()
        yield db_session


def insert(db: Session, **values: object) -> int:
    """Insert a row with plain SQL, past the model's own types, the way a
    hand edit or a buggy query would. Returns its id. A JPEG note on form 1
    by default."""
    row = {
        "health_form_id": 1,
        "image": FAKE_JPEG,
        "content_type": "image/jpeg",
        "staff_user_id": 1,
        "created_at": "2026-11-05 09:00:00.000000",
        **values,
    }
    result = db.execute(
        text(
            "INSERT INTO doctor_notes (health_form_id, image, content_type,"
            " staff_user_id, created_at) VALUES (:health_form_id, :image,"
            " :content_type, :staff_user_id, :created_at) RETURNING id"
        ),
        row,
    )
    return result.scalar_one()


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(
        DoctorNote(
            health_form_id=1,
            image=FAKE_PNG,
            content_type=ImageType.PNG,
            staff_user_id=1,
        )
    )
    db.commit()
    db.expire_all()

    row = db.query(DoctorNote).one()
    assert row.content_type is ImageType.PNG
    assert row.image == FAKE_PNG
    assert row.health_form.id == 1
    assert row.staff.id == 1
    assert row.created_at.tzinfo is not None


@pytest.mark.parametrize(
    "good",
    [
        {},
        {"image": FAKE_PNG, "content_type": "image/png"},
        {"image": b"\xff\xd8\xff" + b"\0" * (IMAGE_MAX_BYTES - 3)},
    ],
)
def test_the_database_accepts_good_rows(db: Session, good: dict[str, object]) -> None:
    insert(db, **good)
    db.commit()


@pytest.mark.parametrize(
    "bad",
    [
        # The opening bytes don't match the type, or aren't an image.
        {"image": FAKE_PNG},
        {"content_type": "image/png"},
        {"image": b"%PDF-1.4 made up"},
        {"image": b""},
        {"image": "\xff\xd8\xff text, not a blob"},
        {"image": b"\xff\xd8\xff" + b"\0" * (IMAGE_MAX_BYTES - 2)},
        {"content_type": "image/gif"},
        {"health_form_id": None},
        {"staff_user_id": None},
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
            text("UPDATE doctor_notes SET staff_user_id = 1 WHERE id = :id"),
            {"id": row_id},
        )
    db.rollback()
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text("DELETE FROM doctor_notes WHERE id = :id"), {"id": row_id})
    db.rollback()
    assert db.query(DoctorNote).count() == 1


def test_the_triggers_exist_at_head(db: Session) -> None:
    triggers = db.scalars(
        text(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'doctor_notes'"
        )
    ).all()
    assert sorted(triggers) == ["doctor_notes_no_delete", "doctor_notes_no_update"]
