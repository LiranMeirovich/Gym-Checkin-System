"""Punch cards: buying one, the customer's active card and its balance, and
their card history (design doc: "Punch cards"; decision 0042).

A card has ``CARD_ENTRIES`` entries for one price, copied from the price
table when it's bought. Bought in month X, it counts until the end of month
X+1: ``expires_on`` is the 1st of month X+2, an Israel-local date, and unused
entries are lost then. Its balance is never stored: it's ``CARD_ENTRIES``
minus the check-ins charged to it.

A card is **active** on a day while it hasn't expired and has entries left.
A customer has at most one: no card is bought while one is active. A card
never sits alongside a monthly or tri-monthly plan: it's bought only at a
check-in whose month no plan covers (``app.core.checkins``), and
``app.core.plans`` refuses every choice and correction while a card is
active.

A card is bought only at a check-in, never from the customer page (this
feature's plan, D5); ``app.core.checkins`` charges the entry.

Every function works inside the caller's transaction and never commits. A
staff member's purchase is written to the activity log in the same
transaction; the customer's own purchase on their phone isn't (decision
0021: the log is for staff changes).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
from app.core.clock import to_local, utc_now
from app.core.customers import CustomerInactiveError
from app.core.models import (
    CARD_ENTRIES,
    CheckIn,
    ChosenBy,
    Customer,
    Plan,
    PunchCard,
    StaffUser,
)
from app.core.months import Month
from app.core.prices import PriceNotSetError, price_for


class PunchCardActiveError(ValueError):
    """The customer has an active punch card: no plan choice, correction or
    second card until it runs out or expires. ``card`` is that card."""

    def __init__(self, card: PunchCard) -> None:
        super().__init__(f"punch card {card.id} is active")
        self.card = card


@dataclass(frozen=True)
class CardBalance:
    """A card with how many of its entries are used."""

    card: PunchCard
    entries_used: int

    @property
    def entries_left(self) -> int:
        return CARD_ENTRIES - self.entries_used

    def is_active_on(self, day: date) -> bool:
        """Whether the card counts on the Israel-local ``day``."""
        return day < self.card.expires_on and self.entries_left > 0


def expiry_for(bought: Month) -> date:
    """A card bought in ``bought`` expires on the 1st of the month after
    next: the first day it no longer counts."""
    expired = bought.plus(2)
    return date(expired.year, expired.month, 1)


def card_balance(db: Session, card: PunchCard) -> CardBalance:
    """``card`` with its used entries counted."""
    used = db.scalar(
        select(func.count())
        .select_from(CheckIn)
        .where(CheckIn.punch_card_id == card.id)
    )
    return CardBalance(card, used or 0)


def active_card(
    db: Session, customer: Customer, today: date | None = None
) -> CardBalance | None:
    """The customer's card that counts on ``today`` (Israel-local; now by
    default), or ``None``. At most one can: no card is bought while another
    is active."""
    day = _today() if today is None else today
    newest = db.scalar(
        select(PunchCard)
        .where(PunchCard.customer_id == customer.id, PunchCard.expires_on > day)
        .order_by(PunchCard.id.desc())
        .limit(1)
    )
    if newest is None:
        return None
    balance = card_balance(db, newest)
    return balance if balance.is_active_on(day) else None


def card_history(db: Session, customer: Customer) -> list[CardBalance]:
    """Every card the customer has bought, newest first, with its used
    entries. Only reads, and isn't logged."""
    used = (
        select(CheckIn.punch_card_id, func.count().label("used"))
        .where(CheckIn.punch_card_id.is_not(None))
        .group_by(CheckIn.punch_card_id)
        .subquery()
    )
    rows = db.execute(
        select(PunchCard, func.coalesce(used.c.used, 0))
        .outerjoin(used, used.c.punch_card_id == PunchCard.id)
        .where(PunchCard.customer_id == customer.id)
        .order_by(PunchCard.bought_at.desc(), PunchCard.id.desc())
    ).all()
    return [CardBalance(card, count) for card, count in rows]


def buy_card(
    db: Session,
    customer: Customer,
    month: Month,
    today: date,
    *,
    by: StaffUser | None,
) -> PunchCard:
    """``customer`` buys a card in ``month``, at that month's price: on
    their phone when ``by`` is ``None``, or from staff member ``by`` at a
    manual check-in (logged).

    ``month`` and ``today`` come from the check-in's own reading of the
    clock, so a tap at midnight can't split them. That no plan covers
    ``month`` is the caller's check (``app.core.checkins``).

    Raises ``CustomerInactiveError``, ``PunchCardActiveError`` or
    ``PriceNotSetError``, checked in that order.
    """
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    current = active_card(db, customer, today)
    if current is not None:
        raise PunchCardActiveError(current.card)
    price = price_for(db, Plan.PUNCH_CARD, month)
    if price is None:
        raise PriceNotSetError(Plan.PUNCH_CARD)
    card = PunchCard(
        customer_id=customer.id,
        price_agorot=price.amount_agorot,
        bought_month=month,
        expires_on=expiry_for(month),
        bought_by=ChosenBy.STAFF if by is not None else ChosenBy.CUSTOMER,
        staff_user_id=None if by is None else by.id,
    )
    db.add(card)
    db.flush()
    if by is not None:
        record(
            db,
            by,
            Action.PUNCH_CARD_BUY,
            Target.PUNCH_CARD,
            card.id,
            after={
                "customer_id": customer.id,
                "price_agorot": card.price_agorot,
                "bought_month": str(card.bought_month),
                "expires_on": card.expires_on.isoformat(),
            },
        )
    return card


def _today() -> date:
    return to_local(utc_now()).date()
