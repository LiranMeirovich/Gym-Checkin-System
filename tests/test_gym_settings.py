"""Gym settings: defaults, reading stored values, refusing bad ones, and
updating them."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.gym_settings import (
    GymSettings,
    InvalidSettingsChangeError,
    InvalidStoredSettingError,
    load_gym_settings,
    load_gym_settings_for_editing,
    update_gym_settings,
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

    with pytest.raises(InvalidStoredSettingError, match="gym_nmae: unknown setting"):
        load_gym_settings(db)


def test_text_that_is_not_json_is_refused(db: Session) -> None:
    store(db, gym_name="Example Gym")  # missing the JSON quotes

    with pytest.raises(InvalidStoredSettingError, match="gym_name: not valid JSON"):
        load_gym_settings(db)


def test_a_json_error_does_not_carry_the_stored_text(db: Session) -> None:
    # JSONDecodeError keeps the whole document in .doc, so it must not be
    # chained onto the error that reaches the logs.
    store(db, report_recipients='["private@example.com",')

    with pytest.raises(InvalidStoredSettingError) as caught:
        load_gym_settings(db)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "private@example.com" not in str(caught.value)


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
        # Characters that would change a To: header once the report is sent.
        ("manager_email", '"boss@example.com,x"'),
        ("manager_email", '"Boss <boss@example.com>"'),
        ("manager_email", '"\\"boss\\"@example.com"'),
        ("manager_email", '"boss@example.com\\u0000"'),
        ("manager_email", '"boss@exa mple.com"'),
        ("manager_email", '"boss@-example.com"'),
        ("manager_email", '"boss@example"'),
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


def test_a_name_of_only_spaces_is_refused(db: Session) -> None:
    store(db, gym_name='"   "')

    with pytest.raises(InvalidStoredSettingError, match="gym_name"):
        load_gym_settings(db)


# ── Updating ────────────────────────────────────────────────────────────


def stored_rows(db: Session) -> dict[str, str]:
    db.expire_all()
    return {row.key: row.value for row in db.scalars(select(Setting))}


def test_an_update_is_read_back_by_load(db: Session) -> None:
    update_gym_settings(
        db,
        {
            "gym_name": "Example Gym",
            "report_recipients": ["a@example.com", "b@example.org"],
            "lock_screen_minutes": 10,
        },
    )
    db.commit()

    settings = load_gym_settings(db)
    assert settings.gym_name == "Example Gym"
    assert settings.report_recipients == ("a@example.com", "b@example.org")
    assert settings.lock_screen_minutes == 10
    assert settings.manager_email is None  # untouched, still the default


def test_only_the_changed_keys_get_rows(db: Session) -> None:
    update_gym_settings(db, {"lock_screen_minutes": 10})
    db.commit()

    assert stored_rows(db) == {"lock_screen_minutes": "10"}


def test_values_are_stored_as_plain_json(db: Session) -> None:
    update_gym_settings(
        db, {"gym_name": "מכון כושר", "report_recipients": ["a@example.com"]}
    )
    db.commit()

    assert stored_rows(db) == {
        "gym_name": '"מכון כושר"',  # readable Hebrew, not \u escapes
        "report_recipients": '["a@example.com"]',
    }


def test_surrounding_spaces_are_trimmed_before_storing(db: Session) -> None:
    update_gym_settings(
        db,
        {
            "gym_name": "  Example Gym ",
            "manager_email": " manager@example.com",
            "report_recipients": ["a@example.com  "],
        },
    )
    db.commit()

    assert stored_rows(db) == {
        "gym_name": '"Example Gym"',
        "manager_email": '"manager@example.com"',
        "report_recipients": '["a@example.com"]',
    }


def test_an_existing_value_is_replaced(db: Session) -> None:
    update_gym_settings(db, {"lock_screen_minutes": 10})
    db.commit()
    update_gym_settings(db, {"lock_screen_minutes": 15})
    db.commit()

    assert load_gym_settings(db).lock_screen_minutes == 15


def test_none_clears_an_optional_setting(db: Session) -> None:
    update_gym_settings(db, {"gym_name": "Example Gym"})
    db.commit()
    update_gym_settings(db, {"gym_name": None})
    db.commit()

    assert load_gym_settings(db).gym_name is None
    # The row is gone, so the setting follows the default again.
    assert stored_rows(db) == {}


@pytest.mark.parametrize(
    "address",
    [
        "manager@example.com",
        "first.last+gym@mail.example.co.il",
        "o'brien@my-gym.example.com",
        "MANAGER@EXAMPLE.COM",
    ],
)
def test_ordinary_addresses_are_accepted(db: Session, address: str) -> None:
    update_gym_settings(db, {"manager_email": address})
    db.commit()

    assert load_gym_settings(db).manager_email == address


def test_a_load_after_a_save_in_the_same_transaction_sees_the_new_value(
    db: Session,
) -> None:
    store(db, lock_screen_minutes="5")
    # Something earlier in the request holds the row, so the session keeps
    # it (unreferenced objects are dropped and would be re-read anyway).
    held = db.get_one(Setting, "lock_screen_minutes")

    update_gym_settings(db, {"lock_screen_minutes": 10})

    assert load_gym_settings(db).lock_screen_minutes == 10
    assert held.value == "10"


def test_none_is_refused_for_a_required_setting(db: Session) -> None:
    with pytest.raises(InvalidSettingsChangeError) as caught:
        update_gym_settings(db, {"lock_screen_minutes": None})

    assert set(caught.value.problems) == {"lock_screen_minutes"}


def test_storing_the_same_value_again_leaves_updated_at_alone(db: Session) -> None:
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    db.add(Setting(key="lock_screen_minutes", value="10", updated_at=long_ago))
    db.commit()

    update_gym_settings(db, {"lock_screen_minutes": 10})
    db.commit()

    db.expire_all()
    assert db.get_one(Setting, "lock_screen_minutes").updated_at == long_ago


def test_one_bad_change_means_nothing_is_written(db: Session) -> None:
    with pytest.raises(InvalidSettingsChangeError) as caught:
        update_gym_settings(
            db,
            {
                "gym_name": "Example Gym",
                "report_recipients": ["a@example.com", "nope"],
                "lock_screen_minutes": 0,
            },
        )
    db.commit()

    assert set(caught.value.problems) == {
        "report_recipients.1",
        "lock_screen_minutes",
    }
    assert stored_rows(db) == {}


def test_an_unknown_key_is_refused_and_nothing_is_written(db: Session) -> None:
    with pytest.raises(InvalidSettingsChangeError) as caught:
        update_gym_settings(db, {"gym_name": "Example Gym", "gym_nmae": "typo"})
    db.commit()

    assert set(caught.value.problems) == {"gym_nmae"}
    assert stored_rows(db) == {}


def test_change_errors_do_not_repeat_the_values(db: Session) -> None:
    with pytest.raises(InvalidSettingsChangeError) as caught:
        update_gym_settings(db, {"report_recipients": ["private@example", "x"]})

    assert "private@example" not in str(caught.value)
    assert "private@example" not in " ".join(caught.value.problems.values())


def test_a_bad_row_written_by_hand_can_be_fixed_by_an_update(db: Session) -> None:
    store(db, lock_screen_minutes='"five"')

    update_gym_settings(db, {"lock_screen_minutes": 5})
    db.commit()

    assert load_gym_settings(db).lock_screen_minutes == 5


# ── Loading for the settings screen ─────────────────────────────────────


def test_editing_load_shows_the_default_for_a_bad_row_and_says_why(
    db: Session,
) -> None:
    store(
        db,
        gym_name='"Example Gym"',
        lock_screen_minutes='"five"',
        report_recipients="[broken",
        gym_nmae='"typo"',
    )

    settings, problems = load_gym_settings_for_editing(db)

    assert settings.gym_name == "Example Gym"  # good rows still load
    assert settings.lock_screen_minutes == 5  # the default
    assert settings.report_recipients == ()
    assert set(problems) == {"lock_screen_minutes", "report_recipients", "gym_nmae"}
    assert problems["report_recipients"] == "not valid JSON"
    assert problems["gym_nmae"] == "unknown setting"


def test_editing_load_reports_nothing_when_every_row_is_good(db: Session) -> None:
    store(db, gym_name='"Example Gym"')

    assert load_gym_settings_for_editing(db) == (
        GymSettings(gym_name="Example Gym"),
        {},
    )


def test_editing_load_problems_do_not_repeat_the_values(db: Session) -> None:
    store(db, report_recipients='["private@example.com", "broken"]')

    _, problems = load_gym_settings_for_editing(db)

    assert set(problems) == {"report_recipients.1"}
    assert "private@example.com" not in " ".join(problems.values())


def test_the_screen_flow_repairs_a_bad_row(db: Session) -> None:
    store(db, lock_screen_minutes='"five"')
    _, problems = load_gym_settings_for_editing(db)
    assert "lock_screen_minutes" in problems

    update_gym_settings(db, {"lock_screen_minutes": 7})
    db.commit()

    assert load_gym_settings_for_editing(db) == (
        GymSettings(lock_screen_minutes=7),
        {},
    )
