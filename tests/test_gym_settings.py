"""Gym settings: defaults, reading stored values, and refusing bad ones."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.gym_settings import (
    GymSettings,
    InvalidStoredSettingError,
    load_gym_settings,
)
from app.core.models import Setting


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def store(db: Session, **rows: str) -> None:
    """Write raw JSON text straight into the table, as a hand edit would."""
    db.add_all(Setting(key=key, value=value) for key, value in rows.items())
    db.commit()


# ── Defaults ────────────────────────────────────────────────────────────


def test_an_empty_table_gives_the_defaults(db: Session) -> None:
    settings = load_gym_settings(db)

    assert settings == GymSettings()
    assert settings.gym_name is None
    assert settings.manager_email is None
    assert settings.report_recipients == ()
    assert settings.lock_screen_minutes == 5


def test_stored_values_override_only_their_own_defaults(db: Session) -> None:
    store(db, gym_name='"Example Gym"')

    settings = load_gym_settings(db)

    assert settings.gym_name == "Example Gym"
    assert settings.lock_screen_minutes == 5


# ── Reading stored values ───────────────────────────────────────────────


def test_every_type_reads_back_from_json(db: Session) -> None:
    store(
        db,
        gym_name='"Example Gym"',
        manager_email='"manager@example.com"',
        report_recipients='["a@example.com", "b@example.org"]',
        lock_screen_minutes="10",
    )

    assert load_gym_settings(db) == GymSettings(
        gym_name="Example Gym",
        manager_email="manager@example.com",
        report_recipients=("a@example.com", "b@example.org"),
        lock_screen_minutes=10,
    )


def test_hebrew_text_reads_back_unchanged(db: Session) -> None:
    store(db, gym_name='"\\u05de\\u05db\\u05d5\\u05df \\u05db\\u05d5\\u05e9\\u05e8"')

    assert load_gym_settings(db).gym_name == "מכון כושר"


def test_loaded_settings_cannot_be_changed(db: Session) -> None:
    settings = load_gym_settings(db)

    with pytest.raises(ValidationError):
        settings.lock_screen_minutes = 1  # type: ignore[misc]


# ── Refusing bad rows ───────────────────────────────────────────────────


def test_an_unknown_key_is_refused(db: Session) -> None:
    store(db, gym_nmae='"Example Gym"')

    with pytest.raises(InvalidStoredSettingError, match="unknown setting 'gym_nmae'"):
        load_gym_settings(db)


def test_text_that_is_not_json_is_refused(db: Session) -> None:
    store(db, gym_name="Example Gym")  # missing the JSON quotes

    with pytest.raises(InvalidStoredSettingError, match="'gym_name' is not valid JSON"):
        load_gym_settings(db)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("lock_screen_minutes", '"5"'),  # a string, not a number
        ("lock_screen_minutes", "true"),  # a bool is not a number either
        ("lock_screen_minutes", "5.5"),
        ("lock_screen_minutes", "0"),
        ("lock_screen_minutes", "61"),
        ("gym_name", '""'),
        ("gym_name", "5"),
        ("manager_email", '"not an email"'),
        ("manager_email", '"two@at@example.com"'),
        ("report_recipients", '"a@example.com"'),  # a string, not a list
        ("report_recipients", '["a@example.com", "A@example.com"]'),
        ("report_recipients", '["a@example.com", "nope"]'),
    ],
)
def test_an_invalid_value_is_refused_not_replaced_by_the_default(
    db: Session, key: str, value: str
) -> None:
    store(db, **{key: value})

    with pytest.raises(InvalidStoredSettingError, match=key):
        load_gym_settings(db)


def test_error_messages_do_not_repeat_stored_addresses(db: Session) -> None:
    store(db, report_recipients='["private@example.com", "broken"]')

    with pytest.raises(InvalidStoredSettingError) as caught:
        load_gym_settings(db)

    assert "private@example.com" not in str(caught.value)
    assert "broken" not in str(caught.value)
