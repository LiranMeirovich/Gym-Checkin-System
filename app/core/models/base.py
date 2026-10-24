"""What every model shares: the declarative ``Base`` and the UTC timestamp
column type."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

# Every constraint and index gets a predictable name. SQLite can't alter a
# table in place, so Alembic rebuilds it ("batch" mode) and has to find
# constraints by name; unnamed ones can't be dropped or changed later.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """A timestamp stored in UTC.

    Writing (or comparing against) a naive datetime is an error, and every
    value read back is timezone-aware UTC. SQLite stores it as fixed-width
    text ("2026-10-24 09:02:00.000000"), so sorting and comparing the text
    in SQL gives the same order as the times.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: store timezone-aware UTC times")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """The base class of every table model. Alembic compares its metadata
    with the migrations to find schema changes."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # A ``Mapped[datetime]`` column is a UTCDateTime unless it says
    # otherwise, so forgetting the type can't store a naive local time.
    type_annotation_map = {datetime: UTCDateTime}
