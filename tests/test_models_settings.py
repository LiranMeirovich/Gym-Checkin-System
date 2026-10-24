"""The settings table model: rows round-trip and ``updated_at`` follows
changes."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Setting


def test_a_row_round_trips_with_an_aware_timestamp(migrated_db: Path) -> None:
    with Session(get_engine()) as session, session.begin():
        session.add(Setting(key="gym_name", value='"Example Gym"'))

    with Session(get_engine()) as session:
        row = session.get_one(Setting, "gym_name")
        assert row.value == '"Example Gym"'
        assert row.updated_at.tzinfo is UTC


def test_changing_a_value_refreshes_updated_at(migrated_db: Path) -> None:
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    with Session(get_engine()) as session, session.begin():
        session.add(Setting(key="lock_screen_minutes", value="5", updated_at=long_ago))

    with Session(get_engine()) as session, session.begin():
        session.get_one(Setting, "lock_screen_minutes").value = "10"

    with Session(get_engine()) as session:
        assert session.get_one(Setting, "lock_screen_minutes").updated_at > long_ago
