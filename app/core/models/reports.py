"""The ``reports`` table: one row per generation of a month's report
(design doc: "Monthly report").

``rows_json`` is the snapshot the report was made from: the rows
``app.core.reports.calculate()`` returned, as JSON. The preview, the Excel
file and the PDF all come from it, so what the manager sees is what the
files hold. The total isn't stored (it's the rows' sum), and neither are the
files' paths (they follow from the month).

Regenerating adds a row; the newest row for a month is that month's report.
Rows are only ever added, never changed or deleted (triggers in the
migration refuse both). Delivery steps (emailed, approved, sent) will be
rows of their own that name a generation, not columns here.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.staff import StaffUser
from app.core.months import Month


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        # A real month in YYYY-MM, as on ``punch_cards.bought_month``.
        CheckConstraint(
            "length(month) = 7"
            " AND month >= '1000-01'"
            " AND date(month || '-01') IS month || '-01'",
            name="month_is_a_month",
        ),
        CheckConstraint("json_valid(rows_json)", name="rows_are_json"),
        # The newest generation of a month.
        Index(None, "month", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[Month]
    generated_at: Mapped[datetime] = mapped_column(default=utc_now)
    # Who pressed Generate; empty when the scheduled job made it.
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))
    rows_json: Mapped[str] = mapped_column(Text)

    staff: Mapped[StaffUser | None] = relationship()
