"""Check-ins (design doc: "Check-in flow", "The monthly choice"; decisions
0004, 0017, 0025).

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

The phone path is here; the manual path (feature 4) shares the same order,
and punch cards (upcoming) slot into step 3: a covering plan first, then an
active card, then the plan page.

Every function works inside the caller's transaction and never commits.
A customer checking in on their own phone is not a staff change and isn't
written to the activity log (decision 0021).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

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
)
from app.core.months import Month
from app.core.plans import (
    PlanOption,
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
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    # One reading of the clock for the whole check-in: the form's day, the
    # month, the repeat window and the plan choice all follow from it.
    now = utc_now()
    local_now = to_local(now)
    today = local_now.date()
    form = health_form_status(db, customer, today)
    if not form.allows_check_in:
        raise HealthFormRequiredError(form)

    month = Month.of(today)
    # A repeat only within this month: the first visit of a month is never
    # swallowed by a late visit the evening before, so it still gets the
    # plan page and is counted in its own month.
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent = _recent(db, customer, after=now - REPEAT_WINDOW, from_=month_start)
    if recent is not None:
        device.last_seen_at = now
        db.flush()
        return CheckInResult(
            Outcome.ALREADY_CHECKED_IN, recent, covering_choice(db, customer, month)
        )

    covering = covering_choice(db, customer, month)
    if covering is None:
        if plan is None:
            raise PlanRequiredError(month, plan_options(db, customer, month))
        covering = choose_plan_by_customer(db, customer, plan, month)

    check_in = CheckIn(
        customer_id=customer.id,
        checked_in_at=now,
        method=CheckInMethod.PHONE,
        device_session_id=device.id,
    )
    db.add(check_in)
    device.last_seen_at = now
    db.flush()
    return CheckInResult(Outcome.CHECKED_IN, check_in, covering)


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
