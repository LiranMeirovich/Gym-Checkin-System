"""Table models. Each area of the schema gets its own module here; import
every model module in this file so ``Base.metadata`` (and Alembic) sees all
tables."""

from app.core.models.activity_log import ActivityLogEntry
from app.core.models.base import Base, MonthColumn, UTCDateTime
from app.core.models.checkins import CheckIn, CheckInMethod
from app.core.models.customers import Customer
from app.core.models.doctor_notes import DoctorNote, ImageType
from app.core.models.health_form_acceptances import HealthFormAcceptance
from app.core.models.health_forms import HealthForm
from app.core.models.phone_links import DeviceSession, LinkCode
from app.core.models.plan_choices import ChosenBy, PlanChoice
from app.core.models.prices import Plan, Price
from app.core.models.settings import Setting
from app.core.models.staff import StaffUser
from app.core.models.staff_sessions import StaffSession

__all__ = [
    "ActivityLogEntry",
    "Base",
    "CheckIn",
    "CheckInMethod",
    "ChosenBy",
    "Customer",
    "DeviceSession",
    "DoctorNote",
    "HealthForm",
    "HealthFormAcceptance",
    "ImageType",
    "LinkCode",
    "MonthColumn",
    "Plan",
    "PlanChoice",
    "Price",
    "Setting",
    "StaffSession",
    "StaffUser",
    "UTCDateTime",
]
