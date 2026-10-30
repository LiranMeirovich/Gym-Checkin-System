"""Prices: what a plan costs in a month, and the manager's price changes
(design doc: "Plans, prices and billing").

Prices are only ever added. A change applies from its ``valid_from_month`` on,
until a later month's change; among rows for the same month the newest wins,
so correcting a typo or cancelling an upcoming change is one more row. A price
can't start in a past month, so what a past month cost never changes, and
choices keep their own copy of the price anyway.

There are no default prices: until the manager enters one, ``price_for`` finds
nothing, and the caller has to say so rather than guess an amount.

Every function works inside the caller's transaction and never commits. Each
added price is written to the activity log in the same transaction, with
``by``, the staff member making it, as the actor; a price that's already in
effect for that month adds nothing. Whether ``by`` may make the change is the
route's check (``require_permission``), not this module's.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
from app.core.models import AgeGroup, Plan, Price, StaffUser
from app.core.months import Month

# How far ahead a change can start; anything later is a typo in the year.
MAX_MONTHS_AHEAD = 24
# ₪10,000. Refuses an amount typed with a few extra digits.
MAX_AMOUNT_AGOROT = 1_000_000
MONTH_FIELD = "valid_from_month"


@dataclass(frozen=True)
class PriceChange:
    """One price in a save: this plan and age group cost this much."""

    plan: Plan
    age_group: AgeGroup
    amount_agorot: int

    @property
    def field(self) -> str:
        """The name a refusal uses for this price."""
        return f"{self.plan.value}.{self.age_group.value}"


class InvalidPricesError(ValueError):
    """One or more parts of a save break their rule. ``fields`` lists every
    one of them at once, so a form can mark them all: ``MONTH_FIELD``, or a
    ``PriceChange.field``. Nothing was saved."""

    def __init__(self, fields: set[str]) -> None:
        super().__init__("invalid: " + ", ".join(sorted(fields)))
        self.fields = frozenset(fields)


@dataclass(frozen=True)
class PriceInEffect:
    """One cell of the price table. ``price`` is ``None`` if it's not set."""

    plan: Plan
    age_group: AgeGroup
    price: Price | None


@dataclass(frozen=True)
class PriceOverview:
    """Everything the Prices screen shows."""

    current_month: Month
    # All plan and age group pairs, in a fixed order.
    current: list[PriceInEffect]
    # The change waiting for each later month, soonest first. A row replaced
    # by a newer one for the same month isn't here.
    upcoming: list[Price]
    # Every row ever entered, latest month first, newest first within it.
    history: list[Price]


def price_for(
    db: Session, plan: Plan, age_group: AgeGroup, month: Month
) -> Price | None:
    """The price that applies to ``month``, or ``None`` if none does yet."""
    return db.scalar(
        select(Price)
        .where(
            Price.plan == plan,
            Price.age_group == age_group,
            Price.valid_from_month <= month,
        )
        .order_by(Price.valid_from_month.desc(), Price.id.desc())
        .limit(1)
    )


def price_overview(db: Session) -> PriceOverview:
    """The prices in effect this month, upcoming changes and the history."""
    today = Month.current()
    history = list(
        db.scalars(
            select(Price).order_by(Price.valid_from_month.desc(), Price.id.desc())
        )
    )
    # Oldest first, so a later row replaces an earlier one in both.
    in_effect: dict[tuple[Plan, AgeGroup], Price] = {}
    upcoming: dict[tuple[Plan, AgeGroup, Month], Price] = {}
    for row in reversed(history):
        if row.valid_from_month <= today:
            in_effect[row.plan, row.age_group] = row
        else:
            upcoming[row.plan, row.age_group, row.valid_from_month] = row
    return PriceOverview(
        current_month=today,
        current=[
            PriceInEffect(plan, age_group, in_effect.get((plan, age_group)))
            for plan in Plan
            for age_group in AgeGroup
        ],
        upcoming=[
            upcoming[plan, age_group, month]
            for month in sorted({month for _, _, month in upcoming})
            for plan in Plan
            for age_group in AgeGroup
            if (plan, age_group, month) in upcoming
        ],
        history=history,
    )


def set_prices(
    db: Session,
    valid_from_month: Month,
    changes: Iterable[PriceChange],
    *,
    by: StaffUser,
) -> list[Price]:
    """Apply these prices from ``valid_from_month`` on, all or none. Returns
    the rows added: a price already in effect for that month adds nothing.

    The month is this month or up to ``MAX_MONTHS_AHEAD`` later. Choosing this
    month doesn't touch choices already made: they keep their copied price.

    Raises ``InvalidPricesError``.
    """
    changes = list(changes)
    _check(valid_from_month, changes)
    added = []
    for change in changes:
        previous = price_for(db, change.plan, change.age_group, valid_from_month)
        if previous is not None and previous.amount_agorot == change.amount_agorot:
            continue
        price = Price(
            plan=change.plan,
            age_group=change.age_group,
            amount_agorot=change.amount_agorot,
            valid_from_month=valid_from_month,
        )
        db.add(price)
        db.flush()
        record(
            db,
            by,
            Action.PRICE_ADD,
            Target.PRICE,
            price.id,
            before=(
                None if previous is None else {"amount_agorot": previous.amount_agorot}
            ),
            after={
                "plan": change.plan.value,
                "age_group": change.age_group.value,
                "amount_agorot": change.amount_agorot,
                "valid_from_month": str(valid_from_month),
            },
        )
        added.append(price)
    return added


def _check(valid_from_month: Month, changes: list[PriceChange]) -> None:
    invalid: set[str] = set()
    today = Month.current()
    if not today <= valid_from_month <= today.plus(MAX_MONTHS_AHEAD):
        invalid.add(MONTH_FIELD)
    seen: set[str] = set()
    for change in changes:
        # bool is an int too, but it isn't an amount.
        if (
            not isinstance(change.amount_agorot, int)
            or isinstance(change.amount_agorot, bool)
            or not 1 <= change.amount_agorot <= MAX_AMOUNT_AGOROT
            # Two amounts for one price: neither can be the one meant.
            or change.field in seen
        ):
            invalid.add(change.field)
        seen.add(change.field)
    if invalid:
        raise InvalidPricesError(invalid)
