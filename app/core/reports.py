"""The monthly report: what each customer pays for a month, worked out from
history only (design doc: "Monthly report"; decisions 0042, 0043).

One row per customer with something to pay or covered that month. Each
thing they had in the month is a **charge**:

- **Monthly**: its price; it ends on the month's last day.
- **Tri-monthly**: its full price in its first month, 0 in the other two;
  it ends on the third month's last day.
- **Single entry**: the month's check-ins not charged to a punch card,
  times its price; no end date. A 10-minute repeat is never stored, so it
  never counts.
- **Punch card bought this month**: its price; it ends on its last valid
  day (the day before ``expires_on``, as the screens show it).
- **Punch card bought last month** that still had entries left on this
  month's 1st: 0, with the same end date.

Plan choices are read with ``app.core.plans.is_active()``: a choice counts
while nothing replaces it, and a "no plan" row covers nothing (decision
0026). Prices are the ones copied onto the choice or the card, never the
price table, so a past month regenerates the same.

A customer with two charges in one month (a card that ran out, then a
plan) gets one row: the payments added up, the plan types in the order they
were made, and the end date of the latest one.

This module only reads, inside the caller's transaction.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import start_of_local_day
from app.core.models import CARD_ENTRIES, CheckIn, Customer, Plan, PlanChoice, PunchCard
from app.core.months import Month
from app.core.plans import is_active


@dataclass(frozen=True)
class ReportRow:
    """One customer's line in a month's report."""

    customer_id: int
    first_name: str
    last_name: str
    # Every plan the customer had in the month, in the order they were made.
    plans: tuple[Plan, ...]
    payment_agorot: int
    # The latest plan's end; ``None`` when that's single entry.
    ends_on: date | None


@dataclass(frozen=True)
class MonthReport:
    month: Month
    rows: tuple[ReportRow, ...]

    @property
    def total_agorot(self) -> int:
        return sum(row.payment_agorot for row in self.rows)


@dataclass(frozen=True)
class _Charge:
    plan: Plan
    payment_agorot: int
    ends_on: date | None
    # When the choice was made or the card bought: orders a row's charges.
    made_at: datetime
    made_id: int


def calculate(db: Session, month: Month) -> MonthReport:
    """The report for ``month``, from the plan choices, punch cards and
    check-ins on record. Rows are sorted by last name, then first name."""
    starts = start_of_local_day(_first_day(month))
    ends = start_of_local_day(_first_day(month.plus(1)))
    charges: dict[int, list[_Charge]] = defaultdict(list)
    for customer_id, charge in [
        *_plan_charges(db, month, starts, ends),
        *_card_charges(db, month, starts),
    ]:
        charges[customer_id].append(charge)
    customers = db.scalars(select(Customer).where(Customer.id.in_(charges))).all()
    rows = [_row(customer, charges[customer.id]) for customer in customers]
    rows.sort(key=lambda row: (row.last_name, row.first_name, row.customer_id))
    return MonthReport(month, tuple(rows))


def _plan_charges(
    db: Session, month: Month, starts: datetime, ends: datetime
) -> list[tuple[int, _Charge]]:
    """The active plan choice covering ``month``, for each customer who has
    one (at most one each, decision 0025)."""
    choices = db.scalars(
        select(PlanChoice).where(
            PlanChoice.plan.is_not(None),
            PlanChoice.start_month <= month,
            PlanChoice.end_month >= month,
            is_active(),
        )
    ).all()
    visits = _single_entry_visits(db, starts, ends)
    result = []
    for choice in choices:
        plan, price = choice.plan, choice.unit_price_agorot
        # A real choice always has both (the ``no_plan_row_is_complete`` CHECK).
        if plan is None or price is None:
            raise ValueError(f"plan choice {choice.id} has no plan or price")
        if plan is Plan.MONTHLY:
            payment, ends_on = price, _last_day(month)
        elif plan is Plan.TRI_MONTHLY:
            payment = price if choice.start_month == month else 0
            ends_on = _last_day(choice.end_month)
        else:
            payment, ends_on = visits.get(choice.customer_id, 0) * price, None
        charge = _Charge(plan, payment, ends_on, choice.chosen_at, choice.id)
        result.append((choice.customer_id, charge))
    return result


def _single_entry_visits(
    db: Session, starts: datetime, ends: datetime
) -> dict[int, int]:
    """Each customer's check-ins between ``starts`` and ``ends`` that no
    punch card paid for."""
    rows = db.execute(
        select(CheckIn.customer_id, func.count())
        .where(
            CheckIn.checked_in_at >= starts,
            CheckIn.checked_in_at < ends,
            CheckIn.punch_card_id.is_(None),
        )
        .group_by(CheckIn.customer_id)
    ).all()
    return {customer_id: count for customer_id, count in rows}


def _card_charges(
    db: Session, month: Month, starts: datetime
) -> list[tuple[int, _Charge]]:
    """Cards bought in ``month`` at their price, and cards bought the month
    before that still had entries on ``month``'s 1st, at 0."""
    used_before = (
        select(func.count())
        .select_from(CheckIn)
        .where(CheckIn.punch_card_id == PunchCard.id, CheckIn.checked_in_at < starts)
        .scalar_subquery()
    )
    rows = db.execute(
        select(PunchCard, used_before).where(
            PunchCard.bought_month.in_([month, month.plus(-1)])
        )
    ).all()
    result = []
    for card, used in rows:
        if card.bought_month == month:
            payment = card.price_agorot
        elif used < CARD_ENTRIES:
            payment = 0
        else:
            continue
        ends_on = card.expires_on - timedelta(days=1)
        charge = _Charge(Plan.PUNCH_CARD, payment, ends_on, card.bought_at, card.id)
        result.append((card.customer_id, charge))
    return result


def _row(customer: Customer, charges: list[_Charge]) -> ReportRow:
    ordered = sorted(charges, key=lambda c: (c.made_at, c.plan, c.made_id))
    return ReportRow(
        customer_id=customer.id,
        first_name=customer.first_name,
        last_name=customer.last_name,
        plans=tuple(charge.plan for charge in ordered),
        payment_agorot=sum(charge.payment_agorot for charge in ordered),
        ends_on=ordered[-1].ends_on,
    )


def _first_day(month: Month) -> date:
    return date(month.year, month.month, 1)


def _last_day(month: Month) -> date:
    return _first_day(month.plus(1)) - timedelta(days=1)
