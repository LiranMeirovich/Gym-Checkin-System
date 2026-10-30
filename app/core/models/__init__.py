"""Table models. Each area of the schema gets its own module here; import
every model module in this file so ``Base.metadata`` (and Alembic) sees all
tables."""

from app.core.models.activity_log import ActivityLogEntry
from app.core.models.base import Base, MonthColumn, UTCDateTime
from app.core.models.customers import Customer
from app.core.models.prices import AgeGroup, Plan, Price
from app.core.models.settings import Setting
from app.core.models.staff import StaffUser
from app.core.models.staff_sessions import StaffSession

__all__ = [
    "ActivityLogEntry",
    "AgeGroup",
    "Base",
    "Customer",
    "MonthColumn",
    "Plan",
    "Price",
    "Setting",
    "StaffSession",
    "StaffUser",
    "UTCDateTime",
]
