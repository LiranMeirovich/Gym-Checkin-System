"""The ``report_deliveries`` table: one row per step in delivering a
generation of a month's report (design doc: "Monthly report").

A generation (a ``reports`` row) is emailed to the manager, approved, and
emailed to the recipients. Each of those, and each retry, is a row here
naming the generation, never a column on ``reports`` (decision 0044). The
newest rows for a month's newest generation are where its report stands; a
regeneration is a new generation with no rows yet, so it starts unapproved.

- ``manager_email`` and ``recipients_email``: one sending attempt each,
  ``sent`` or ``failed``, with the addresses it went to at the time (the
  recipients in Settings can change before a retry). The cause of a failure
  goes to the server log, not here.
- ``approval``: the manager approved this generation. Always names who.

Steps by the scheduled job name no staff member. Rows are only ever added,
never changed or deleted (triggers in the migration refuse both).
"""

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.reports import Report
from app.core.models.staff import StaffUser


class DeliveryKind(enum.StrEnum):
    MANAGER_EMAIL = "manager_email"
    APPROVAL = "approval"
    RECIPIENTS_EMAIL = "recipients_email"


class EmailOutcome(enum.StrEnum):
    SENT = "sent"
    FAILED = "failed"


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )


class ReportDelivery(Base):
    __tablename__ = "report_deliveries"
    __table_args__ = (
        # An email has an outcome and its addresses; an approval has
        # neither. "IS", not "=": a NULL CHECK would pass.
        CheckConstraint(
            "(kind = 'approval') IS (outcome IS NULL)",
            name="email_has_an_outcome",
        ),
        CheckConstraint(
            "(kind = 'approval') IS (recipients_json IS NULL)",
            name="email_has_recipients",
        ),
        CheckConstraint(
            "recipients_json IS NULL"
            " OR (json_valid(recipients_json)"
            " AND json_type(recipients_json) = 'array')",
            name="recipients_are_a_json_list",
        ),
        # The scheduled job never approves: an approval names who.
        CheckConstraint(
            "kind != 'approval' OR staff_user_id IS NOT NULL",
            name="approval_names_staff",
        ),
        # A generation's newest steps.
        Index(None, "report_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: reports are never deleted.
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"))
    kind: Mapped[DeliveryKind] = mapped_column(_enum(DeliveryKind, "kind"))
    outcome: Mapped[EmailOutcome | None] = mapped_column(_enum(EmailOutcome, "outcome"))
    # The addresses an email went to, as a JSON list.
    recipients_json: Mapped[str | None] = mapped_column(Text)
    # Who did it; empty when the scheduled job did.
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))
    at: Mapped[datetime] = mapped_column(default=utc_now)

    report: Mapped[Report] = relationship()
    staff: Mapped[StaffUser | None] = relationship()
