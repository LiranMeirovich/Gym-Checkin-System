"""The ``plan_choices`` table: one row per plan chosen for a customer (design
doc: "Plans, prices and billing", "Data model").

A choice covers ``start_month`` to ``end_month``: one month, or three for
tri-monthly. Its price is copied in when it's made, so later
price changes never reach it and past reports regenerate identically.

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both). A correction is a new row whose ``replaces_id``
points at the choice it replaces; a choice is active while no row replaces
it. Another trigger refuses a row that would give a customer-month two
active choices, and another keeps a correction on the months of the choice
it replaces.

A "no plan" row clears a choice: it replaces it and has no plan or price,
so the months it names are covered by nothing and can be chosen
again. The rules the database can't check (which months can be
chosen, where the price comes from) live in ``app.core.plans``.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.prices import Plan
from app.core.models.staff import StaffUser
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
        # A "no plan" row takes its months from the choice it clears (a
        # trigger checks that).
        CheckConstraint(
            "plan IS NULL OR end_month IS CASE plan"
            " WHEN 'tri_monthly'"
            " THEN substr(date(start_month || '-01', '+2 months'), 1, 7)"
            " ELSE start_month END",
            name="months_match_plan",
        ),
        CheckConstraint(
            "unit_price_agorot IS NULL"
            " OR (typeof(unit_price_agorot) = 'integer' AND unit_price_agorot >= 0)",
            name="unit_price_is_whole_agorot",
        ),
        # A real choice has a plan and a price; a "no plan" row has neither
        # and always clears an earlier choice.
        CheckConstraint(
            "(plan IS NULL) = (unit_price_agorot IS NULL)"
            " AND (plan IS NOT NULL OR replaces_id IS NOT NULL)",
            name="no_plan_row_is_complete",
        ),
        # A staff member's choice says who; a customer's names no one.
        CheckConstraint(
            "(chosen_by = 'staff') = (staff_user_id IS NOT NULL)",
            name="staff_choice_names_staff",
        ),
        # The plans a month can be chosen for: never a punch card, which
        # has its own table (decision 0042). Written out rather than made by
        # the Enum, which would allow every ``Plan``; the same name and
        # values as before punch cards existed.
        CheckConstraint(
            "\"plan\" IN ('monthly', 'tri_monthly', 'single_entry')", name="plan"
        ),
        Index(None, "customer_id", "start_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    # ``None`` on a "no plan" row.
    plan: Mapped[Plan | None] = mapped_column(
        Enum(
            Plan,
            name="plan",
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda plans: [plan.value for plan in plans],
        )
    )
    start_month: Mapped[Month]
    end_month: Mapped[Month]
    # The whole price for monthly and tri-monthly; per visit for single entry.
    unit_price_agorot: Mapped[int | None] = mapped_column(Integer)
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

    # Who chose it, when staff did; for the customer page's history.
    staff: Mapped[StaffUser | None] = relationship()
