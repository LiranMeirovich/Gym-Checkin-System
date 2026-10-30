"""The ``prices`` table: the manager's price table, one row per price change
(design doc: "Plans, prices and billing", "Data model").

Rows are only ever added, so the table is also the price history. The row
that applies to a month is the one with the latest ``valid_from_month`` up to
that month, and among rows for the same month the newest (highest ``id``): a
correction or a cancelled change is a new row too. The rules the database
can't check (which months can be chosen, sensible amounts) live in
``app.core.prices``.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.months import Month


class Plan(StrEnum):
    """What a customer can choose for a month. The values are what the
    database stores."""

    MONTHLY = "monthly"
    TRI_MONTHLY = "tri_monthly"
    SINGLE_ENTRY = "single_entry"


class AgeGroup(StrEnum):
    """Which of a plan's two prices applies. The values are what the database
    stores."""

    ADULT = "adult"
    UNDER_18 = "under_18"


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (
        # Whole agorot only: SQLite would otherwise keep 1.5 as it is, even
        # in an INTEGER column. Free is the core rules' call, not this one's.
        CheckConstraint(
            "typeof(amount_agorot) = 'integer' AND amount_agorot >= 0",
            name="amount_is_whole_agorot",
        ),
        # A real month in YYYY-MM, from the year 1000 on as ``Month`` requires.
        # "IS", not "=": date() of anything else is NULL, and a NULL CHECK
        # would pass.
        CheckConstraint(
            "length(valid_from_month) = 7"
            " AND valid_from_month >= '1000-01'"
            " AND date(valid_from_month || '-01') IS valid_from_month || '-01'",
            name="valid_from_month_is_a_month",
        ),
        Index(None, "plan", "age_group", "valid_from_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan: Mapped[Plan] = mapped_column(
        Enum(
            Plan,
            name="plan",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda plans: [plan.value for plan in plans],
        )
    )
    age_group: Mapped[AgeGroup] = mapped_column(
        Enum(
            AgeGroup,
            name="age_group",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda groups: [group.value for group in groups],
        )
    )
    amount_agorot: Mapped[int] = mapped_column(Integer)
    valid_from_month: Mapped[Month]
    # When it was entered, for the history. Who entered it is in the activity
    # log.
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
