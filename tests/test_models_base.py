"""The shared model base: the UTC timestamp type and naming conventions.

Uses its own throwaway table and metadata, so nothing here ends up in
``Base.metadata`` (which Alembic compares against the migrations).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    Engine,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    insert,
    select,
)
from sqlalchemy.exc import StatementError

from app.core.db import create_db_engine
from app.core.models import Base, UTCDateTime
from app.core.models.base import NAMING_CONVENTION

metadata = MetaData()
event = Table(
    "event",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("at", UTCDateTime, nullable=True),
)

ISRAEL_SUMMER = timezone(timedelta(hours=3))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(tmp_path / "test.db")
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_aware_datetime_is_stored_as_utc_and_read_back_aware(engine: Engine) -> None:
    # 12:30 in Israel summer time is 09:30 UTC.
    with engine.begin() as connection:
        connection.execute(
            insert(event).values(at=datetime(2026, 6, 1, 12, 30, tzinfo=ISRAEL_SUMMER))
        )

    with engine.connect() as connection:
        raw = connection.exec_driver_sql("SELECT at FROM event").scalar()
        loaded = connection.execute(select(event.c.at)).scalar_one()

    assert raw == "2026-06-01 09:30:00.000000"
    assert loaded == datetime(2026, 6, 1, 9, 30, tzinfo=UTC)
    assert loaded.tzinfo is UTC


def test_null_stays_null(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(insert(event).values(at=None))

    with engine.connect() as connection:
        assert connection.execute(select(event.c.at)).scalar_one() is None


def test_naive_datetime_is_refused_on_write(engine: Engine) -> None:
    with pytest.raises(StatementError, match="naive"), engine.begin() as connection:
        connection.execute(insert(event).values(at=datetime(2026, 6, 1, 12, 30)))


def test_naive_datetime_is_refused_in_comparisons(engine: Engine) -> None:
    query = select(event).where(event.c.at > datetime(2026, 6, 1))

    with pytest.raises(StatementError, match="naive"), engine.connect() as connection:
        connection.execute(query)


def test_comparisons_follow_time_order(engine: Engine) -> None:
    # Two times in different offsets, inserted out of order.
    later = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    earlier = datetime(2026, 6, 1, 12, 30, tzinfo=ISRAEL_SUMMER)  # 09:30 UTC
    with engine.begin() as connection:
        connection.execute(insert(event), [{"at": later}, {"at": earlier}])

    with engine.connect() as connection:
        ordered = connection.execute(select(event.c.at).order_by(event.c.at)).scalars()
        after_945 = connection.execute(
            select(event.c.at).where(
                event.c.at > datetime(2026, 6, 1, 9, 45, tzinfo=UTC)
            )
        ).scalars()

        assert list(ordered) == [earlier, later]
        assert list(after_945) == [later]


def test_datetime_annotations_map_to_utc_datetime() -> None:
    assert Base.registry.type_annotation_map[datetime] is UTCDateTime


def test_constraints_get_conventional_names() -> None:
    conventional = MetaData(naming_convention=NAMING_CONVENTION)
    Table("parent", conventional, Column("id", Integer, primary_key=True))
    child = Table(
        "child",
        conventional,
        Column("id", Integer, primary_key=True),
        Column("parent_id", ForeignKey("parent.id"), index=True),
        Column("code", Integer, unique=True),
    )

    names = {constraint.name for constraint in child.constraints}
    names |= {index.name for index in child.indexes}

    assert names == {
        "pk_child",
        "fk_child_parent_id_parent",
        "uq_child_code",
        "ix_child_parent_id",
    }
    assert Base.metadata.naming_convention == NAMING_CONVENTION
