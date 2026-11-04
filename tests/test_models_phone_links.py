"""The link_codes and device_sessions table models: defaults, and the
checks the database itself enforces. Names and numbers are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Customer, DeviceSession, LinkCode, StaffUser
from app.core.permissions import Role

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# Not a hash of anything; it only has to look like one to pass the CHECK.
HASH = "a" * 64
OTHER_HASH = "b" * 64
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        session.add_all(
            [
                StaffUser(
                    id=1, display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH
                ),
                Customer(
                    id=1,
                    first_name="Noa",
                    last_name="Levi",
                    phone="+972501234567",
                    date_of_birth=date(1990, 5, 1),
                ),
            ]
        )
        session.flush()
        yield session


def insert_code(db: Session, **values: object) -> None:
    """Insert a link code with plain SQL, past the model's own types."""
    row = {
        "customer_id": 1,
        "code_hash": HASH,
        "created_by": 1,
        "created_at": "2026-11-03 09:00:00.000000",
        "expires_at": "2026-11-03 09:15:00.000000",
        **values,
    }
    db.execute(
        text(
            "INSERT INTO link_codes (customer_id, code_hash, created_by,"
            " created_at, expires_at) VALUES (:customer_id, :code_hash,"
            " :created_by, :created_at, :expires_at)"
        ),
        row,
    )
    db.flush()


def insert_device(db: Session, **values: object) -> None:
    """Insert a device session with plain SQL, past the model's own types."""
    row = {
        "customer_id": 1,
        "token_hash": HASH,
        "user_agent": "Mozilla/5.0",
        "created_at": "2026-11-03 09:00:00.000000",
        "last_seen_at": "2026-11-03 09:00:00.000000",
        **values,
    }
    db.execute(
        text(
            "INSERT INTO device_sessions (customer_id, token_hash, user_agent,"
            " created_at, last_seen_at) VALUES (:customer_id, :token_hash,"
            " :user_agent, :created_at, :last_seen_at)"
        ),
        row,
    )
    db.flush()


def test_a_new_link_code_gets_its_defaults(db: Session) -> None:
    db.add(
        LinkCode(
            customer_id=1,
            code_hash=HASH,
            created_by=1,
            expires_at=datetime(2999, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()

    row = db.query(LinkCode).one()
    assert row.used_at is None
    assert row.created_at.tzinfo is UTC
    assert row.customer.first_name == "Noa"
    assert row.staff.display_name == "Dana"


def test_a_new_device_session_gets_its_defaults(db: Session) -> None:
    db.add(DeviceSession(customer_id=1, token_hash=HASH))
    db.commit()

    row = db.query(DeviceSession).one()
    assert row.user_agent == ""
    assert row.revoked_at is None
    assert row.created_at.tzinfo is UTC
    assert row.last_seen_at.tzinfo is UTC


@pytest.mark.parametrize(
    "values",
    [
        {"code_hash": "123456"},
        {"code_hash": "A" * 64},
        {"code_hash": "a" * 63 + "g"},
        {"expires_at": "2026-11-03 09:00:00.000000"},
        {"expires_at": "2026-11-03 08:59:00.000000"},
        {"customer_id": 99},
        {"created_by": 99},
    ],
    ids=str,
)
def test_the_database_refuses_bad_link_codes(db: Session, values: dict) -> None:
    with pytest.raises(IntegrityError):
        insert_code(db, **values)


@pytest.mark.parametrize(
    "values",
    [
        {"token_hash": "a-plain-token"},
        {"token_hash": "a" * 65},
        {"user_agent": "x" * 201},
        {"customer_id": 99},
    ],
    ids=str,
)
def test_the_database_refuses_bad_device_sessions(db: Session, values: dict) -> None:
    with pytest.raises(IntegrityError):
        insert_device(db, **values)


def test_a_user_agent_of_200_characters_fits(db: Session) -> None:
    insert_device(db, user_agent="x" * 200)


def test_two_device_sessions_cannot_share_a_token(db: Session) -> None:
    insert_device(db)
    insert_device(db, token_hash=OTHER_HASH)
    with pytest.raises(IntegrityError):
        insert_device(db)


def test_codes_may_share_a_hash(db: Session) -> None:
    # 6 digits repeat; codes are found through their customer, not the hash.
    insert_code(db)
    insert_code(db)
    assert db.query(LinkCode).count() == 2


def test_a_revoked_session_keeps_its_row(db: Session) -> None:
    db.add(DeviceSession(customer_id=1, token_hash=HASH, revoked_at=NOW))
    db.commit()
    assert db.query(DeviceSession).one().revoked_at == NOW
