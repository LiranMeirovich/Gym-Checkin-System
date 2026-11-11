"""Plans: what covers a customer in a month, what each plan would cost them,
choosing one, and correcting or clearing it (design doc: "Plans, prices and
billing"; decisions 0017, 0022, 0025).

A choice covers its month, or three months for tri-monthly. It's active
while no later row replaces it (``replaces_id``), and a customer-month has
at most one active choice: this module refuses a second one, and a database
trigger backs that up. The price is copied onto the choice when it's made,
so later price changes never reach it.

A correction is a new row that replaces a choice, from the same start
month. Clearing is a "no plan" row: it replaces the choice, has no plan or
price, and covers nothing, so its months are free to choose again. Only a
choice starting in the current month can be corrected; one that started
earlier is already in a past month's report.

Each plan has one price, the same for every customer (decision 0036).

A punch card is priced like a plan but isn't one: it's bought into its own
table (``app.core.punch_cards``), never chosen here. While a customer has an
active card, every choice and correction is refused, single entry and
clearing included, so a card never sits alongside a plan (decision 0042).

A customer chooses their own plan on their phone, for the month of the
check-in it comes with (``choose_plan_by_customer``), under the same rules
as staff; the row names no staff member.

Every function works inside the caller's transaction and never commits.
Each staff choice is written to the activity log in the same transaction,
with ``by``, the staff member making it, as the actor; a customer's own
choice is not logged (decision 0021: the log is for staff changes).
Whether ``by`` may make it is the route's check (``require_permission``),
not this module's.
"""

from dataclasses import dataclass

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.orm import Session, aliased

from app.core.activity_log import Action, Target, record
from app.core.customers import CustomerInactiveError
from app.core.models import (
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    Price,
    StaffUser,
)
from app.core.months import Month
from app.core.prices import PriceNotSetError, price_for
from app.core.punch_cards import PunchCardActiveError, active_card

# How many months each plan covers, counting the one it's chosen in. These
# are the plans a month can be chosen for: a punch card isn't one.
MONTHS_COVERED = {Plan.MONTHLY: 1, Plan.TRI_MONTHLY: 3, Plan.SINGLE_ENTRY: 1}


class MonthNotChoosableError(ValueError):
    """Staff choose a plan for the current month only."""


class NotAChoiceError(ValueError):
    """A punch card is bought at a check-in, never chosen for a month
    (decision 0042)."""


class ChoiceReplacedError(ValueError):
    """The choice was already corrected or cleared (often a page left open).
    ``replacement`` is the row that replaced it."""

    def __init__(self, replacement: PlanChoice) -> None:
        super().__init__(f"already replaced by plan choice {replacement.id}")
        self.replacement = replacement


class NotCorrectableError(ValueError):
    """Only a choice starting in the current month can be corrected. A "no
    plan" row can't be either: choose a plan for the month instead."""


class NoChangeError(ValueError):
    """The correction would give the same plan at the same price."""


class MonthCoveredError(ValueError):
    """A month the plan would cover already has an active choice.
    ``choice`` is that choice; changing it is a correction."""

    def __init__(self, choice: PlanChoice) -> None:
        super().__init__(f"already covered by plan choice {choice.id}")
        self.choice = choice


@dataclass(frozen=True)
class PlanOption:
    """One plan as offered for a month. ``price`` is ``None`` if it's not
    set, and then the plan can't be chosen."""

    plan: Plan
    price: Price | None


@dataclass(frozen=True)
class PlanOverview:
    """Everything the customer page shows about plans."""

    current_month: Month
    # The active choice covering this month, or ``None``.
    covering: PlanChoice | None
    # Whether ``covering`` may be corrected or cleared (``is_correctable``).
    correctable: bool
    # Every plan that can be chosen here, with its price for this month, in
    # a fixed order. Never a punch card: it's bought only at a check-in.
    options: list[PlanOption]
    # Every choice ever made for the customer, latest month first, newest
    # first within it, replaced ones and "no plan" rows included.
    history: list[PlanChoice]
    # For each replaced choice in ``history``, the id of the row that
    # replaced it.
    replaced_by: dict[int, int]


def end_month(plan: Plan, start: Month) -> Month:
    """The last month a choice of ``plan`` made in ``start`` covers."""
    return start.plus(MONTHS_COVERED[plan] - 1)


def plan_options(db: Session, month: Month) -> list[PlanOption]:
    """Each plan that can be chosen for a month, with what it costs in
    ``month``: what the customer page offers."""
    return [PlanOption(plan, price_for(db, plan, month)) for plan in MONTHS_COVERED]


def check_in_options(db: Session, month: Month) -> list[PlanOption]:
    """What a check-in with no plan offers: the plans, then the punch
    card, each with what it costs in ``month``."""
    return [PlanOption(plan, price_for(db, plan, month)) for plan in Plan]


def covering_choice(db: Session, customer: Customer, month: Month) -> PlanChoice | None:
    """The active choice that covers ``month``, or ``None``."""
    return _first_active(db, customer, month, month)


def is_correctable(choice: PlanChoice) -> bool:
    """Whether ``choice``'s months allow a correction: it has a plan and
    starts in the current month. One that started earlier is in a past
    month's report. (Being replaced already is ``correct_plan``'s check.)"""
    return choice.plan is not None and choice.start_month == Month.current()


def choice_of(db: Session, customer: Customer, choice_id: int) -> PlanChoice | None:
    """``customer``'s choice ``choice_id``, or ``None`` if it isn't theirs."""
    return db.scalar(
        select(PlanChoice).where(
            PlanChoice.id == choice_id, PlanChoice.customer_id == customer.id
        )
    )


def plan_overview(db: Session, customer: Customer) -> PlanOverview:
    """This month's plan, the plans on offer, and the customer's history."""
    today = Month.current()
    history = list(
        db.scalars(
            select(PlanChoice)
            .where(PlanChoice.customer_id == customer.id)
            .order_by(PlanChoice.start_month.desc(), PlanChoice.id.desc())
        )
    )
    covering = covering_choice(db, customer, today)
    return PlanOverview(
        current_month=today,
        covering=covering,
        correctable=covering is not None and is_correctable(covering),
        options=plan_options(db, today),
        history=history,
        # A correction is always the same customer's (a trigger checks), so
        # the history holds both ends of every replacement.
        replaced_by={
            row.replaces_id: row.id for row in history if row.replaces_id is not None
        },
    )


def choose_plan(
    db: Session, customer: Customer, plan: Plan, month: Month, *, by: StaffUser
) -> PlanChoice:
    """Choose ``plan`` for ``customer`` from ``month``, at this month's
    price.

    Raises ``CustomerInactiveError``, ``MonthNotChoosableError``,
    ``NotAChoiceError``, ``PunchCardActiveError``, ``MonthCoveredError`` or
    ``PriceNotSetError``, checked in that order.
    """
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    if month != Month.current():
        raise MonthNotChoosableError(f"{month} is not the current month")
    return choose_plan_at_check_in(db, customer, plan, month, by=by)


def choose_plan_at_check_in(
    db: Session, customer: Customer, plan: Plan, month: Month, *, by: StaffUser
) -> PlanChoice:
    """Staff member ``by`` chooses ``plan`` for ``customer`` from ``month``,
    as part of a manual check-in (``app.core.checkins``). Logged like any
    staff choice.

    ``month`` is the check-in's own month, worked out by the caller from
    the same "now" as the visit, so it isn't checked against the clock
    again (as with ``choose_plan_by_customer``).

    Raises ``CustomerInactiveError``, ``NotAChoiceError``,
    ``PunchCardActiveError``, ``MonthCoveredError`` or ``PriceNotSetError``,
    checked in that order.
    """
    choice = _new_choice(db, customer, plan, month, by=by)
    record(
        db, by, Action.PLAN_CHOOSE, Target.PLAN_CHOICE, choice.id, after=_logged(choice)
    )
    return choice


def choose_plan_by_customer(
    db: Session, customer: Customer, plan: Plan, month: Month
) -> PlanChoice:
    """``customer`` chooses ``plan`` themselves, on their phone, from
    ``month`` (design doc: "The monthly choice"). The same rules as a staff
    choice; the row names no staff member.

    ``month`` is the month of the check-in this choice comes with, worked
    out by the caller from the same "now" as the check-in itself. Reading
    the clock again here could land in the next month at midnight, and
    give the visit's month no plan (``app.core.checkins``).

    Not written to the activity log: the log is for staff changes, and the
    customer acting for themselves is not one (as with linking a phone).

    Raises ``CustomerInactiveError``, ``NotAChoiceError``,
    ``PunchCardActiveError``, ``MonthCoveredError`` or ``PriceNotSetError``,
    checked in that order.
    """
    return _new_choice(db, customer, plan, month, by=None)


def _new_choice(
    db: Session, customer: Customer, plan: Plan, month: Month, *, by: StaffUser | None
) -> PlanChoice:
    """Check and add a new choice of ``plan`` from ``month``: by staff
    member ``by``, or by the customer when ``by`` is ``None``. Which months
    may be chosen is the caller's check."""
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    _refuse_a_card(db, customer, plan)
    last = end_month(plan, month)
    covered = _first_active(db, customer, month, last)
    if covered is not None:
        raise MonthCoveredError(covered)
    price = price_for(db, plan, month)
    if price is None:
        raise PriceNotSetError(plan)
    choice = PlanChoice(
        customer_id=customer.id,
        plan=plan,
        start_month=month,
        end_month=last,
        unit_price_agorot=price.amount_agorot,
        chosen_by=ChosenBy.STAFF if by is not None else ChosenBy.CUSTOMER,
        staff_user_id=None if by is None else by.id,
    )
    db.add(choice)
    db.flush()
    return choice


def correct_plan(
    db: Session,
    customer: Customer,
    choice: PlanChoice,
    plan: Plan | None,
    *,
    by: StaffUser,
) -> PlanChoice:
    """Replace ``customer``'s ``choice`` with ``plan`` from the same start
    month, at this month's price, or clear it with a
    "no plan" row if ``plan`` is ``None``. Returns the new row.

    Raises ``CustomerInactiveError``, ``NotAChoiceError``,
    ``PunchCardActiveError``, ``ChoiceReplacedError``,
    ``NotCorrectableError``, ``MonthCoveredError``, ``PriceNotSetError`` or
    ``NoChangeError``, checked in that order.
    """
    if choice.customer_id != customer.id:
        raise ValueError(f"plan choice {choice.id} isn't customer {customer.id}'s")
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    _refuse_a_card(db, customer, plan)
    replacement = db.scalar(
        select(PlanChoice).where(PlanChoice.replaces_id == choice.id)
    )
    if replacement is not None:
        raise ChoiceReplacedError(replacement)
    if not is_correctable(choice):
        raise NotCorrectableError(
            "only a choice with a plan, starting this month, can be corrected"
        )
    month = choice.start_month

    if plan is None:
        action = Action.PLAN_CLEAR
        new = PlanChoice(
            customer_id=customer.id,
            plan=None,
            start_month=month,
            end_month=choice.end_month,
            unit_price_agorot=None,
            chosen_by=ChosenBy.STAFF,
            staff_user_id=by.id,
            replaces_id=choice.id,
        )
    else:
        action = Action.PLAN_CORRECT
        last = end_month(plan, month)
        covered = _first_active(db, customer, month, last, besides=choice)
        if covered is not None:
            raise MonthCoveredError(covered)
        price = price_for(db, plan, month)
        if price is None:
            raise PriceNotSetError(plan)
        if (plan, price.amount_agorot) == (choice.plan, choice.unit_price_agorot):
            raise NoChangeError(f"plan choice {choice.id} is already that")
        new = PlanChoice(
            customer_id=customer.id,
            plan=plan,
            start_month=month,
            end_month=last,
            unit_price_agorot=price.amount_agorot,
            chosen_by=ChosenBy.STAFF,
            staff_user_id=by.id,
            replaces_id=choice.id,
        )
    db.add(new)
    db.flush()
    record(
        db,
        by,
        action,
        Target.PLAN_CHOICE,
        new.id,
        before={"id": choice.id, **_logged(choice)},
        after={**_logged(new), "replaces_id": choice.id},
    )
    return new


def _refuse_a_card(db: Session, customer: Customer, plan: Plan | None) -> None:
    """A punch card is never a choice, and nothing is chosen or corrected
    while the customer has an active card (decision 0042)."""
    if plan is not None and plan not in MONTHS_COVERED:
        raise NotAChoiceError(f"{plan.value} isn't chosen for a month")
    card = active_card(db, customer)
    if card is not None:
        raise PunchCardActiveError(card.card)


def _logged(choice: PlanChoice) -> dict[str, object]:
    """How a choice reads in the activity log."""
    return {
        "customer_id": choice.customer_id,
        "plan": None if choice.plan is None else choice.plan.value,
        "start_month": str(choice.start_month),
        "end_month": str(choice.end_month),
        "unit_price_agorot": choice.unit_price_agorot,
    }


def is_active() -> ColumnElement[bool]:
    """True for a choice no later row replaces. The report reads choices
    with this same rule."""
    replacement = aliased(PlanChoice)
    return ~exists().where(replacement.replaces_id == PlanChoice.id)


def _first_active(
    db: Session,
    customer: Customer,
    start: Month,
    end: Month,
    *,
    besides: PlanChoice | None = None,
) -> PlanChoice | None:
    """The earliest active choice covering any month from ``start`` to
    ``end``, leaving out ``besides`` (the choice a correction replaces).
    There's at most one per month. "No plan" rows cover nothing."""
    query = select(PlanChoice).where(
        PlanChoice.customer_id == customer.id,
        PlanChoice.plan.is_not(None),
        PlanChoice.start_month <= end,
        PlanChoice.end_month >= start,
        is_active(),
    )
    if besides is not None:
        query = query.where(PlanChoice.id != besides.id)
    return db.scalar(query.order_by(PlanChoice.start_month).limit(1))
