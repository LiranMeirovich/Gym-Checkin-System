"""Check-ins (design doc: "Check-in flow", "Manual check-in", "The monthly
choice"; decisions 0004, 0017, 0025, 0032).

Every check-in runs the same checks in order:

1. **A signed health form** that hasn't expired on the day, in Israel
   time. Without one, nothing is recorded (``HealthFormRequiredError``):
   the gym isn't insured (decision 0004). A form waiting for a doctor's
   note lets the customer in; the manager reviews it (decision 0041).
2. **Not a repeat:** a second check-in by the same customer within
   ``REPEAT_WINDOW`` of the last one, by any method, in the same month, is
   "already checked in". Nothing new is recorded, so it doesn't count as
   another single entry. A first visit just after midnight on the 1st is
   never a repeat of the evening before: it belongs to the new month.
3. **A plan covering this month, or else an active punch card.** A card
   that counts today pays for the visit with one entry, in any month,
   with no plan page. With neither, the phone shows the plan page
   (``PlanRequiredError``, with the plans and the punch card); the option
   the customer taps comes back with the next call, which chooses the plan
   (or buys the card and uses its first entry) and checks in, in the same
   transaction. An option sent when the month is already covered, or a
   card already counts (another phone, or the manager, got there first),
   is ignored: the customer checks in under what covers them.
4. **Recorded**, and the phone counts as used (``last_seen_at``).

A manual check-in at the desk (``check_in_manually``) runs the same order,
records the staff member instead of a phone, and differs only at step 3:
a staff member who may choose plans (the manager) is asked for one, like
the phone, and may also sell a punch card; anyone else (an instructor)
gets single entry for the month, chosen in their name (decision 0017). An
active card pays for the visit whoever checks the customer in. A price
that isn't set refuses it either way (``PriceNotSetError``). The
single-entry price is always set in practice, so that refusal has no
fallback of its own.

Every function works inside the caller's transaction and never commits.
A customer checking in on their own phone is not a staff change and isn't
written to the activity log (decision 0021); a manual check-in is.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.activity_log import Action, Target, record
from app.core.clock import start_of_local_day, to_local, utc_now
from app.core.customers import CustomerInactiveError
from app.core.health_forms import HealthFormStatus, health_form_status
from app.core.models import (
    CheckIn,
    CheckInMethod,
    Customer,
    DeviceSession,
    Plan,
    PlanChoice,
    PunchCard,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Permission, has_permission
from app.core.plans import (
    PlanOption,
    check_in_options,
    choose_plan_at_check_in,
    choose_plan_by_customer,
    covering_choice,
)
from app.core.punch_cards import CardBalance, active_card, buy_card, card_balance

# A check-in this soon after the last one is "already checked in" (design
# doc: "Rules the code and database enforce").
REPEAT_WINDOW = timedelta(minutes=10)
# How many check-ins the customer page shows (decision 0037).
HISTORY_LENGTH = 10


class HealthFormRequiredError(ValueError):
    """The customer has no signed health form today: never signed, or the
    newest has expired."""

    def __init__(self, status: HealthFormStatus) -> None:
        super().__init__(f"health form is {status.state.value}")
        self.status = status


class PlanRequiredError(ValueError):
    """No plan covers ``month``, no punch card counts today, and nothing was
    chosen. ``options`` are the plans and the punch card with their prices;
    one without a price can't be chosen."""

    def __init__(self, month: Month, options: list[PlanOption]) -> None:
        super().__init__(f"no plan covers {month}")
        self.month = month
        self.options = options


class PlanNotAllowedError(ValueError):
    """A staff member without ``plans.choose`` sent a plan with a manual
    check-in. Instructors never choose plans (decision 0017)."""


class Outcome(StrEnum):
    CHECKED_IN = "checked_in"
    # Within REPEAT_WINDOW of the last check-in; nothing new was recorded.
    ALREADY_CHECKED_IN = "already_checked_in"


@dataclass(frozen=True)
class CheckInResult:
    outcome: Outcome
    # The new check-in, or the recent one this repeats.
    check_in: CheckIn
    # The plan covering this month, never a "no plan" row. ``None`` when a
    # punch card paid for the visit, or for a repeat whose month has since
    # lost its plan (the manager cleared it).
    plan: PlanChoice | None
    # The punch card this visit used an entry of, with its balance after
    # it; for a repeat, the card the first visit used. ``None`` otherwise.
    card: CardBalance | None = None


def check_in_by_phone(
    db: Session, device: DeviceSession, plan: Plan | None = None
) -> CheckInResult:
    """Check in the customer whose phone is ``device``, choosing ``plan``
    first if no plan covers this month.

    Raises ``CustomerInactiveError``, ``HealthFormRequiredError``,
    ``PlanRequiredError`` or ``PriceNotSetError`` (the chosen plan or card
    has no price), checked in that order. Nothing is recorded when it
    raises.
    """
    customer = device.customer
    visit = _first_checks(db, customer)
    if visit.recent is not None:
        device.last_seen_at = visit.now
        db.flush()
        return _repeat(db, customer, visit.month, visit.recent)

    covering, card = _what_pays(db, customer, visit, plan, by=None)
    check_in = CheckIn(
        customer_id=customer.id,
        checked_in_at=visit.now,
        method=CheckInMethod.PHONE,
        device_session_id=device.id,
        punch_card_id=None if card is None else card.id,
    )
    db.add(check_in)
    device.last_seen_at = visit.now
    db.flush()
    return _checked_in(db, check_in, covering, card)


def check_in_manually(
    db: Session, customer: Customer, *, by: StaffUser, plan: Plan | None = None
) -> CheckInResult:
    """Staff member ``by`` checks ``customer`` in at the desk. If no plan
    covers this month and no punch card counts today, ``by`` chooses
    ``plan`` (or sells a punch card) when they may choose plans, and gets
    single entry when they may not (decision 0017). A plan sent when the
    customer is already covered is ignored, as on the phone.

    Raises ``PlanNotAllowedError`` (a plan sent by someone who may not
    choose one), then ``CustomerInactiveError``,
    ``HealthFormRequiredError``, ``PlanRequiredError`` or
    ``PriceNotSetError``, in that order. Nothing is recorded or logged
    when it raises, nor for a repeat.
    """
    may_choose = has_permission(by.role, Permission.PLANS_CHOOSE)
    if plan is not None and not may_choose:
        raise PlanNotAllowedError("only staff who choose plans may send one")
    visit = _first_checks(db, customer)
    if visit.recent is not None:
        return _repeat(db, customer, visit.month, visit.recent)

    if not may_choose:
        plan = Plan.SINGLE_ENTRY
    covering, card = _what_pays(db, customer, visit, plan, by=by)
    check_in = CheckIn(
        customer_id=customer.id,
        checked_in_at=visit.now,
        method=CheckInMethod.MANUAL,
        staff_user_id=by.id,
        punch_card_id=None if card is None else card.id,
    )
    db.add(check_in)
    db.flush()
    record(
        db,
        by,
        Action.CHECKIN_MANUAL,
        Target.CHECKIN,
        check_in.id,
        after={
            "customer_id": customer.id,
            "plan_choice_id": None if covering is None else covering.id,
            "punch_card_id": None if card is None else card.id,
        },
    )
    return _checked_in(db, check_in, covering, card)


def recent_checkins(
    db: Session, customer: Customer, *, limit: int = HISTORY_LENGTH
) -> list[CheckIn]:
    """The customer's latest check-ins, newest first, by any method. Only
    reads, and isn't logged: it's what every staff member sees on the
    customer page."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return list(
        db.scalars(
            select(CheckIn)
            .where(CheckIn.customer_id == customer.id)
            .order_by(CheckIn.checked_in_at.desc(), CheckIn.id.desc())
            .limit(limit)
        )
    )


def checkins_on(db: Session, day: date) -> list[CheckIn]:
    """Every check-in on the Israel-local ``day``, by any method and any
    customer, newest first, each with its customer loaded. Only reads, and
    isn't logged: it's what every staff member sees on the dashboard, the
    instructor's answer to fake check-ins (design doc: "Fake check-ins")."""
    return list(
        db.scalars(
            select(CheckIn)
            .options(joinedload(CheckIn.customer))
            .where(
                CheckIn.checked_in_at >= start_of_local_day(day),
                CheckIn.checked_in_at < start_of_local_day(day + timedelta(days=1)),
            )
            .order_by(CheckIn.checked_in_at.desc(), CheckIn.id.desc())
        )
    )


@dataclass(frozen=True)
class _Visit:
    """What the first checks found: the one reading of the clock the whole
    check-in uses, its Israel month, and the recent check-in this one
    repeats, if any."""

    now: datetime
    today: date
    month: Month
    recent: CheckIn | None


def _what_pays(
    db: Session,
    customer: Customer,
    visit: _Visit,
    plan: Plan | None,
    *,
    by: StaffUser | None,
) -> tuple[PlanChoice | None, PunchCard | None]:
    """Step 3: the plan covering the visit's month, else the punch card
    that counts today, else ``plan`` chosen (or the card bought) by the
    customer when ``by`` is ``None``, or by staff member ``by``. Exactly
    one of the two comes back.

    Raises ``PlanRequiredError`` when nothing covers the customer and no
    ``plan`` was sent, or what choosing or buying raises."""
    covering = covering_choice(db, customer, visit.month)
    if covering is not None:
        return covering, None
    current = active_card(db, customer, visit.today)
    if current is not None:
        return None, current.card
    if plan is None:
        raise PlanRequiredError(visit.month, check_in_options(db, visit.month))
    if plan is Plan.PUNCH_CARD:
        return None, buy_card(db, customer, visit.month, visit.today, by=by)
    if by is None:
        return choose_plan_by_customer(db, customer, plan, visit.month), None
    return choose_plan_at_check_in(db, customer, plan, visit.month, by=by), None


def _checked_in(
    db: Session,
    check_in: CheckIn,
    covering: PlanChoice | None,
    card: PunchCard | None,
) -> CheckInResult:
    """The answer for a new check-in, with the card's balance after it."""
    return CheckInResult(
        Outcome.CHECKED_IN,
        check_in,
        covering,
        None if card is None else card_balance(db, card),
    )


def _repeat(
    db: Session, customer: Customer, month: Month, recent: CheckIn
) -> CheckInResult:
    """A repeat of ``recent``, with the plan covering ``month`` now, or the
    card ``recent`` used, with its balance now."""
    card = recent.punch_card
    return CheckInResult(
        Outcome.ALREADY_CHECKED_IN,
        recent,
        covering_choice(db, customer, month),
        None if card is None else card_balance(db, card),
    )


def _first_checks(db: Session, customer: Customer) -> _Visit:
    """Steps 1 and 2, shared by every way of checking in: an active
    customer, a signed form that hasn't expired, and whether this is a
    repeat.

    One reading of the clock for the whole check-in: the form's day, the
    month, the repeat window and the plan choice all follow from it, so a
    tap at midnight can't split them across two months.
    """
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    now = utc_now()
    local_now = to_local(now)
    today = local_now.date()
    form = health_form_status(db, customer, today)
    if not form.allows_check_in:
        raise HealthFormRequiredError(form)
    # A repeat only within this month: the first visit of a month is never
    # swallowed by a late visit the evening before, so it still gets the
    # plan page and is counted in its own month.
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent = _recent(db, customer, after=now - REPEAT_WINDOW, from_=month_start)
    return _Visit(now, today, Month.of(today), recent)


def _recent(
    db: Session, customer: Customer, *, after: datetime, from_: datetime
) -> CheckIn | None:
    """The customer's latest check-in, by any method, later than ``after``
    and no earlier than ``from_``."""
    return db.scalar(
        select(CheckIn)
        .where(
            CheckIn.customer_id == customer.id,
            CheckIn.checked_in_at > after,
            CheckIn.checked_in_at >= from_,
        )
        .order_by(CheckIn.checked_in_at.desc(), CheckIn.id.desc())
        .limit(1)
    )
