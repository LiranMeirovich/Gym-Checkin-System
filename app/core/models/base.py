"""What every model shares: the declarative ``Base`` and the UTC timestamp
and calendar month column types."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, MetaData, Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from app.core.months import Month

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

    That only holds if every value is written from Python. SQL's own clock
    (``server_default=func.now()``, ``CURRENT_TIMESTAMP``) writes a shorter
    format ("2026-10-24 09:02:00"), and mixing the two breaks comparisons,
    so these columns never get a SQL-side default: set them with
    ``default=utc_now`` instead. A test checks every model for this.
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


class MonthColumn(TypeDecorator[Month]):
    """A calendar month stored as ``YYYY-MM`` text, so sorting and comparing
    the text in SQL gives the same order as the months. Add a CHECK on each
    column for what bypasses this type (design doc: "Data model")."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Month | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Month | None:
        return None if value is None else Month.parse(value)


class Base(DeclarativeBase):
    """The base class of every table model. Alembic compares its metadata
    with the migrations to find schema changes."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # A ``Mapped[datetime]`` column is a UTCDateTime unless it says
    # otherwise, so forgetting the type can't store a naive local time.
    type_annotation_map = {datetime: UTCDateTime, Month: MonthColumn}
