"""Check-ins (design doc: "Check-in flow", "Manual check-in", "The monthly
choice"; decisions 0004, 0017, 0025, 0032).

Every check-in runs the same checks in order:

1. **A valid health form** on the day, in Israel time. Without one,
   nothing is recorded (``HealthFormRequiredError``): the gym isn't insured
   (decision 0004).
2. **Not a repeat:** a second check-in by the same customer within
   ``REPEAT_WINDOW`` of the last one, by any method, in the same month, is
   "already checked in". Nothing new is recorded, so it doesn't count as
   another single entry. A first visit just after midnight on the 1st is
   never a repeat of the evening before: it belongs to the new month.
3. **A plan covering this month.** If none does, the phone shows the plan
   page (``PlanRequiredError``, with this customer's options); the plan the
   customer taps comes back with the next call, which chooses it and
   checks in, in the same transaction. A plan sent for a month that is
   already covered (another phone, or the manager, got there first) is
   ignored: the customer checks in under the plan that covers it.
4. **Recorded**, and the phone counts as used (``last_seen_at``).

A manual check-in at the desk (``check_in_manually``) runs the same order,
records the staff member instead of a phone, and differs only at step 3:
a staff member who may choose plans (the manager) is asked for one, like
the phone; anyone else (an instructor) gets single entry for the month,
chosen in their name (decision 0017). A price that isn't set refuses it
either way (``PriceNotSetError``). The single-entry price is always set in
practice, so that refusal has no fallback of its own.

Punch cards (upcoming) slot into step 3 of both: a covering plan first,
then an active card, then the plan page or single entry.

Every function works inside the caller's transaction and never commits.
A customer checking in on their own phone is not a staff change and isn't
written to the activity log (decision 0021); a manual check-in is.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
from app.core.clock import to_local, utc_now
from app.core.customers import CustomerInactiveError
from app.core.health_forms import HealthFormStatus, health_form_status
from app.core.models import (
    CheckIn,
    CheckInMethod,
    Customer,
    DeviceSession,
    Plan,
    PlanChoice,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Permission, has_permission
from app.core.plans import (
    PlanOption,
    choose_plan_at_check_in,
    choose_plan_by_customer,
    covering_choice,
    plan_options,
)

# A check-in this soon after the last one is "already checked in" (design
# doc: "Rules the code and database enforce").
REPEAT_WINDOW = timedelta(minutes=10)


class HealthFormRequiredError(ValueError):
    """The customer has no valid health form today (missing, expired, or
    waiting for a doctor's note). ``status`` says which."""

    def __init__(self, status: HealthFormStatus) -> None:
        super().__init__(f"health form is {status.state.value}")
        self.status = status


class PlanRequiredError(ValueError):
    """No plan covers ``month`` and none was chosen. ``options`` are the
    plans with this customer's prices; one without a price can't be
    chosen."""

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
    # The plan covering this month, never a "no plan" row. ``None`` only
    # for a repeat whose month has since lost its plan (the manager
    # cleared it).
    plan: PlanChoice | None


def check_in_by_phone(
    db: Session, device: DeviceSession, plan: Plan | None = None
) -> CheckInResult:
    """Check in the customer whose phone is ``device``, choosing ``plan``
    first if no plan covers this month.

    Raises ``CustomerInactiveError``, ``HealthFormRequiredError``,
    ``PlanRequiredError`` or ``PriceNotSetError`` (the chosen plan has no
    price), checked in that order. Nothing is recorded when it raises.
    """
    customer = device.customer
    visit = _first_checks(db, customer)
    if visit.recent is not None:
        device.last_seen_at = visit.now
        db.flush()
        return _repeat(db, customer, visit.month, visit.recent)

    covering = covering_choice(db, customer, visit.month)
    if covering is None:
        if plan is None:
            raise PlanRequiredError(
                visit.month, plan_options(db, customer, visit.month)
            )
        covering = choose_plan_by_customer(db, customer, plan, visit.month)

    check_in = CheckIn(
        customer_id=customer.id,
        checked_in_at=visit.now,
        method=CheckInMethod.PHONE,
        device_session_id=device.id,
    )
    db.add(check_in)
    device.last_seen_at = visit.now
    db.flush()
    return CheckInResult(Outcome.CHECKED_IN, check_in, covering)


def check_in_manually(
    db: Session, customer: Customer, *, by: StaffUser, plan: Plan | None = None
) -> CheckInResult:
    """Staff member ``by`` checks ``customer`` in at the desk. If no plan
    covers this month, ``by`` chooses ``plan`` when they may choose plans,
    and gets single entry when they may not (decision 0017). A plan sent
    for a month that is already covered is ignored, as on the phone.

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

    covering = covering_choice(db, customer, visit.month)
    if covering is None:
        if not may_choose:
            plan = Plan.SINGLE_ENTRY
        elif plan is None:
            raise PlanRequiredError(
                visit.month, plan_options(db, customer, visit.month)
            )
        covering = choose_plan_at_check_in(db, customer, plan, visit.month, by=by)

    check_in = CheckIn(
        customer_id=customer.id,
        checked_in_at=visit.now,
        method=CheckInMethod.MANUAL,
        staff_user_id=by.id,
    )
    db.add(check_in)
    db.flush()
    record(
        db,
        by,
        Action.CHECKIN_MANUAL,
        Target.CHECKIN,
        check_in.id,
        after={"customer_id": customer.id, "plan_choice_id": covering.id},
    )
    return CheckInResult(Outcome.CHECKED_IN, check_in, covering)


@dataclass(frozen=True)
class _Visit:
    """What the first checks found: the one reading of the clock the whole
    check-in uses, its Israel month, and the recent check-in this one
    repeats, if any."""

    now: datetime
    month: Month
    recent: CheckIn | None


def _repeat(
    db: Session, customer: Customer, month: Month, recent: CheckIn
) -> CheckInResult:
    """A repeat of ``recent``, with the plan covering ``month`` now."""
    return CheckInResult(
        Outcome.ALREADY_CHECKED_IN, recent, covering_choice(db, customer, month)
    )


def _first_checks(db: Session, customer: Customer) -> _Visit:
    """Steps 1 and 2, shared by every way of checking in: an active
    customer, a valid health form today, and whether this is a repeat.

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
    return _Visit(now, Month.of(today), recent)


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
