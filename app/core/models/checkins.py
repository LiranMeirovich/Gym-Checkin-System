"""The ``checkins`` table: one row per visit (design doc: "Check-in flow",
"Data model").

A phone check-in names the device session it came from; a manual one
(milestone 3, feature 4) names the staff member who entered it. Exactly
one of the two is set, which a CHECK enforces.

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both): single-entry billing counts these rows, so past
reports must regenerate identically. A check-in doesn't record which plan
choice it was billed under: a later correction (single entry to monthly)
changes which choice is active, and the report works that out from
``plan_choices``.

A check-in that used a punch card entry names the card
(``punch_card_id``); the card's balance is counted from these rows
(decision 0042). Triggers refuse a card of another customer's and one
entry more than the card has.

The rules the database can't check (a valid health form, the 10-minute
repeat window, a plan for the month, a card that hasn't expired) live in
``app.core.checkins``.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.customers import Customer
from app.core.models.phone_links import DeviceSession
from app.core.models.punch_cards import PunchCard
from app.core.models.staff import StaffUser


class CheckInMethod(StrEnum):
    """How a check-in was made. The values are what the database stores."""

    # The customer's linked phone, from the wall QR.
    PHONE = "phone"
    # A staff member at the desk (feature 4).
    MANUAL = "manual"


class CheckIn(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        # A phone check-in names its phone and no staff member; a manual
        # one names the staff member and no phone.
        CheckConstraint(
            "(method = 'phone') = (device_session_id IS NOT NULL)"
            " AND (method = 'manual') = (staff_user_id IS NOT NULL)",
            name="method_names_its_source",
        ),
        Index(None, "customer_id", "checked_in_at"),
        # Everyone's check-ins in a stretch of time: today's on the
        # dashboard, a month's for the report.
        Index(None, "checked_in_at"),
        # A card's check-ins, for its balance.
        Index(None, "punch_card_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: customers are deactivated, never deleted.
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    checked_in_at: Mapped[datetime] = mapped_column(default=utc_now)
    method: Mapped[CheckInMethod] = mapped_column(
        Enum(
            CheckInMethod,
            name="checkin_method",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda methods: [m.value for m in methods],
        )
    )
    # Set for a phone check-in (a trigger checks it's the same customer's).
    device_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_sessions.id")
    )
    # Set for a manual check-in: who entered it.
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))
    # Set when the visit used one of the customer's punch card entries.
    punch_card_id: Mapped[int | None] = mapped_column(ForeignKey("punch_cards.id"))

    customer: Mapped[Customer] = relationship()
    device: Mapped[DeviceSession | None] = relationship()
    staff: Mapped[StaffUser | None] = relationship()
    punch_card: Mapped[PunchCard | None] = relationship()
