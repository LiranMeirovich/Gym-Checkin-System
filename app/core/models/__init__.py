"""Table models. Each area of the schema gets its own module here; import
every model module in this file so ``Base.metadata`` (and Alembic) sees all
tables."""

from app.core.models.base import Base, UTCDateTime
from app.core.models.settings import Setting
from app.core.models.staff import StaffUser
from app.core.models.staff_sessions import StaffSession

__all__ = ["Base", "Setting", "StaffSession", "StaffUser", "UTCDateTime"]
