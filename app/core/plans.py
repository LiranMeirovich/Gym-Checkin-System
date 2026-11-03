"""Plans: what covers a customer in a month, what each plan would cost them,
and choosing one (design doc: "Plans, prices and billing"; decisions 0017,
0022).

A choice covers its month, or three months for tri-monthly. It's active
while no later row replaces it (``replaces_id``, feature 4's corrections),
and a customer-month has at most one active choice: this module refuses a
second one, and a database trigger backs that up. The price and age group
are copied onto the choice when it's made, so later price changes never
reach it.

The age group comes from the customer's age on the 1st of the month, so
someone who turns 18 mid-month keeps the under-18 price until the next one.

Every function works inside the caller's transaction and never commits.
Each choice is written to the activity log in the same transaction, with
``by``, the staff member making it, as the actor. Whether ``by`` may make
it is the route's check (``require_permission``), not this module's.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.orm import Session, aliased

from app.core.activity_log import Action, Target, record
from app.core.customers import CustomerInactiveError
from app.core.models import (
    AgeGroup,
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    Price,
    StaffUser,
)
from app.core.months import Month
from app.core.prices import price_for

ADULT_AGE = 18
# How many months each plan covers, counting the one it's chosen in.
MONTHS_COVERED = {Plan.MONTHLY: 1, Plan.TRI_MONTHLY: 3, Plan.SINGLE_ENTRY: 1}


class MonthNotChoosableError(ValueError):
    """Staff choose a plan for the current month only."""


class PriceNotSetError(ValueError):
    """The manager hasn't entered this plan's price for this customer's age
    group yet. Nothing is guessed; prices must be entered first."""

    def __init__(self, plan: Plan, age_group: AgeGroup) -> None:
        super().__init__(f"no price for {plan.value} / {age_group.value}")
        self.plan = plan
        self.age_group = age_group


class MonthCoveredError(ValueError):
    """A month the plan would cover already has an active choice.
    ``choice`` is that choice; changing it is a correction."""

    def __init__(self, choice: PlanChoice) -> None:
        super().__init__(f"already covered by plan choice {choice.id}")
        self.choice = choice


@dataclass(frozen=True)
class PlanOption:
    """One plan as offered to a customer for a month. ``price`` is ``None``
    if it's not set, and then the plan can't be chosen."""

    plan: Plan
    age_group: AgeGroup
    price: Price | None


@dataclass(frozen=True)
class PlanOverview:
    """Everything the customer page shows about plans."""

    current_month: Month
    # The active choice covering this month, or ``None``.
    covering: PlanChoice | None
    # Every plan with this customer's price for this month, in a fixed order.
    options: list[PlanOption]
    # Every choice ever made for the customer, latest month first, newest
    # first within it, replaced ones included.
    history: list[PlanChoice]


def age_group_for(date_of_birth: date, month: Month) -> AgeGroup:
    """The customer's age group in ``month``: their age on its 1st."""
    first = date(month.year, month.month, 1)
    age = first.year - date_of_birth.year
    if (first.month, first.day) < (date_of_birth.month, date_of_birth.day):
        age -= 1
    return AgeGroup.UNDER_18 if age < ADULT_AGE else AgeGroup.ADULT


def end_month(plan: Plan, start: Month) -> Month:
    """The last month a choice of ``plan`` made in ``start`` covers."""
    return start.plus(MONTHS_COVERED[plan] - 1)


def plan_options(db: Session, customer: Customer, month: Month) -> list[PlanOption]:
    """Each plan with what it costs this customer in ``month``."""
    age_group = age_group_for(customer.date_of_birth, month)
    return [
        PlanOption(plan, age_group, price_for(db, plan, age_group, month))
        for plan in Plan
    ]


def covering_choice(db: Session, customer: Customer, month: Month) -> PlanChoice | None:
    """The active choice that covers ``month``, or ``None``."""
    return _first_active(db, customer, month, month)


def plan_overview(db: Session, customer: Customer) -> PlanOverview:
    """This month's plan, the plans on offer, and the customer's history."""
    today = Month.current()
    return PlanOverview(
        current_month=today,
        covering=covering_choice(db, customer, today),
        options=plan_options(db, customer, today),
        history=list(
            db.scalars(
                select(PlanChoice)
                .where(PlanChoice.customer_id == customer.id)
                .order_by(PlanChoice.start_month.desc(), PlanChoice.id.desc())
            )
        ),
    )


def choose_plan(
    db: Session, customer: Customer, plan: Plan, month: Month, *, by: StaffUser
) -> PlanChoice:
    """Choose ``plan`` for ``customer`` from ``month``, at this month's price
    for their age group.

    Raises ``CustomerInactiveError``, ``MonthNotChoosableError``,
    ``MonthCoveredError`` or ``PriceNotSetError``, checked in that order.
    """
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    if month != Month.current():
        raise MonthNotChoosableError(f"{month} is not the current month")
    last = end_month(plan, month)
    covered = _first_active(db, customer, month, last)
    if covered is not None:
        raise MonthCoveredError(covered)
    age_group = age_group_for(customer.date_of_birth, month)
    price = price_for(db, plan, age_group, month)
    if price is None:
        raise PriceNotSetError(plan, age_group)
    choice = PlanChoice(
        customer_id=customer.id,
        plan=plan,
        start_month=month,
        end_month=last,
        age_group=age_group,
        unit_price_agorot=price.amount_agorot,
        chosen_by=ChosenBy.STAFF,
        staff_user_id=by.id,
    )
    db.add(choice)
    db.flush()
    record(
        db,
        by,
        Action.PLAN_CHOOSE,
        Target.PLAN_CHOICE,
        choice.id,
        after={
            "customer_id": customer.id,
            "plan": plan.value,
            "start_month": str(month),
            "end_month": str(last),
            "age_group": age_group.value,
            "unit_price_agorot": price.amount_agorot,
        },
    )
    return choice


def _is_active() -> ColumnElement[bool]:
    replacement = aliased(PlanChoice)
    return ~exists().where(replacement.replaces_id == PlanChoice.id)


def _first_active(
    db: Session, customer: Customer, start: Month, end: Month
) -> PlanChoice | None:
    """The earliest active choice covering any month from ``start`` to
    ``end``. There's at most one per month."""
    return db.scalar(
        select(PlanChoice)
        .where(
            PlanChoice.customer_id == customer.id,
            PlanChoice.start_month <= end,
            PlanChoice.end_month >= start,
            _is_active(),
        )
        .order_by(PlanChoice.start_month)
        .limit(1)
    )
