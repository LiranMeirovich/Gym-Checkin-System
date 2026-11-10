"""The ``health_form_acceptances`` table: the manager accepting a health
form that had a "yes" answer without a doctor's note (decision 0041).

A form with any "yes" (``health_forms.needs_doctor_note``) waits for the
manager: a doctor's note (``doctor_notes``) or an acceptance here. Either
makes it count in full. A form is accepted at most once (unique).

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both): who accepted the form, and when, stays on record.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.health_forms import HealthForm
from app.core.models.staff import StaffUser


class HealthFormAcceptance(Base):
    __tablename__ = "health_form_acceptances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: forms are never deleted.
    health_form_id: Mapped[int] = mapped_column(
        ForeignKey("health_forms.id"), unique=True
    )
    # Who accepted it.
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    health_form: Mapped[HealthForm] = relationship()
    staff: Mapped[StaffUser] = relationship()
