"""Table models. Each area of the schema gets its own module here; import
every model module in this file so ``Base.metadata`` (and Alembic) sees all
tables."""

from app.core.models.base import Base, UTCDateTime

__all__ = ["Base", "UTCDateTime"]
