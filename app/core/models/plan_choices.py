"""The ``plan_choices`` table: one row per plan chosen for a customer (design
doc: "Plans, prices and billing", "Data model").

A choice covers ``start_month`` to ``end_month``: one month, or three for
tri-monthly. Its price and age group are copied in when it's made, so later
price changes never reach it and past reports regenerate identically.

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both). A correction is a new row whose ``replaces_id``
points at the choice it replaces; a choice is active while no row replaces
it. Another trigger refuses a row that would give a customer-month two
active choices. The rules the database can't check (which months can be
chosen, where the price comes from) live in ``app.core.plans``.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.prices import AgeGroup, Plan
from app.core.months import Month


class ChosenBy(StrEnum):
    """Who made a choice. The values are what the database stores."""

    # On their phone (milestone 3).
    CUSTOMER = "customer"
    # The manager, or an instructor's single-entry fallback at check-in;
    # ``staff_user_id`` says who.
    STAFF = "staff"


def _is_a_month(column: str) -> str:
    # A real month in YYYY-MM, as on ``prices.valid_from_month``. "IS", not
    # "=": date() of anything else is NULL, and a NULL CHECK would pass.
    return (
        f"length({column}) = 7"
        f" AND {column} >= '1000-01'"
        f" AND date({column} || '-01') IS {column} || '-01'"
    )


class PlanChoice(Base):
    __tablename__ = "plan_choices"
    __table_args__ = (
        CheckConstraint(_is_a_month("start_month"), name="start_month_is_a_month"),
        CheckConstraint(_is_a_month("end_month"), name="end_month_is_a_month"),
        # Tri-monthly covers its month and the next two; the others one month.
        CheckConstraint(
            "end_month IS CASE plan"
            " WHEN 'tri_monthly'"
            " THEN substr(date(start_month || '-01', '+2 months'), 1, 7)"
            " ELSE start_month END",
            name="months_match_plan",
        ),
        CheckConstraint(
            "typeof(unit_price_agorot) = 'integer' AND unit_price_agorot >= 0",
            name="unit_price_is_whole_agorot",
        ),
        # A staff member's choice says who; a customer's names no one.
        CheckConstraint(
            "(chosen_by = 'staff') = (staff_user_id IS NOT NULL)",
            name="staff_choice_names_staff",
        ),
        Index(None, "customer_id", "start_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
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
    start_month: Mapped[Month]
    end_month: Mapped[Month]
    # On the 1st of ``start_month``, from the customer's date of birth.
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
    # The whole price for monthly and tri-monthly; per visit for single entry.
    unit_price_agorot: Mapped[int] = mapped_column(Integer)
    chosen_at: Mapped[datetime] = mapped_column(default=utc_now)
    chosen_by: Mapped[ChosenBy] = mapped_column(
        Enum(
            ChosenBy,
            name="chosen_by",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda who: [w.value for w in who],
        )
    )
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))
    # Unique: a choice is replaced at most once, so two corrections can't
    # both claim it.
    replaces_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_choices.id"), unique=True
    )
