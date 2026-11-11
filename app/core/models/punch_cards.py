"""The ``punch_cards`` table: one row per punch card bought (design doc:
"Punch cards", "Data model"; decision 0042).

A card has ``CARD_ENTRIES`` entries, bought for one price. The price is
copied in when it's bought, so later price changes never reach it and past
reports regenerate identically. Expiry is fixed by the month it was bought:
bought in month X, it's valid to the end of month X+1, and ``expires_on``
is the 1st of month X+2, the first Israel-local day it no longer counts (a
CHECK ties it to ``bought_month``). Unlike ``health_forms.expires_on``,
which is the last valid day.

The balance is never stored: it's ``CARD_ENTRIES`` minus the check-ins
charged to the card (``checkins.punch_card_id``). A trigger on ``checkins``
refuses one entry too many and a check-in charged to another customer's
card.

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both). The rules the database can't check (one active card
at a time, never alongside a monthly or tri-monthly plan, not expired on
the day) live in ``app.core.punch_cards``.
"""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.customers import Customer
from app.core.models.plan_choices import ChosenBy
from app.core.models.staff import StaffUser
from app.core.months import Month

# Entries on every card (decision 0042). The ``checkins`` trigger that
# refuses one too many holds the same number: changing it needs a migration.
CARD_ENTRIES = 20


class PunchCard(Base):
    __tablename__ = "punch_cards"
    __table_args__ = (
        # A real month in YYYY-MM, as on ``prices.valid_from_month``.
        CheckConstraint(
            "length(bought_month) = 7"
            " AND bought_month >= '1000-01'"
            " AND date(bought_month || '-01') IS bought_month || '-01'",
            name="bought_month_is_a_month",
        ),
        # The 1st of the month after next. "IS", not "=": a NULL CHECK
        # would pass.
        CheckConstraint(
            "expires_on IS date(bought_month || '-01', '+2 months')",
            name="expires_after_next_month",
        ),
        CheckConstraint(
            "typeof(price_agorot) = 'integer' AND price_agorot >= 0",
            name="price_is_whole_agorot",
        ),
        # A staff member's purchase says who; a customer's names no one.
        CheckConstraint(
            "(bought_by = 'staff') = (staff_user_id IS NOT NULL)",
            name="staff_purchase_names_staff",
        ),
        Index(None, "customer_id", "bought_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: customers are deactivated, never deleted.
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    # The whole card's price, copied from the price table when bought.
    price_agorot: Mapped[int] = mapped_column(Integer)
    # The Israel month it was bought in; the report charges it there.
    bought_month: Mapped[Month]
    # The first Israel-local day it no longer counts.
    expires_on: Mapped[date]
    bought_at: Mapped[datetime] = mapped_column(default=utc_now)
    bought_by: Mapped[ChosenBy] = mapped_column(
        Enum(
            ChosenBy,
            name="bought_by",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda who: [w.value for w in who],
        )
    )
    # Set when staff bought it at a manual check-in: who.
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))

    customer: Mapped[Customer] = relationship()
    staff: Mapped[StaffUser | None] = relationship()
