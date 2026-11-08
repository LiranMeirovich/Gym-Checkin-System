"""Check-ins by phone and at the desk: the checks in order (health form,
repeat window, a plan for the month), choosing a plan with the check-in, an
instructor's single-entry fallback, and what is recorded and logged.
Names, numbers and amounts are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import checkins, months
from app.core.activity_log import Action, Target
from app.core.checkins import (
    REPEAT_WINDOW,
    HealthFormRequiredError,
    Outcome,
    PlanNotAllowedError,
    PlanRequiredError,
    check_in_by_phone,
    check_in_manually,
)
from app.core.customers import CustomerInactiveError
from app.core.db import get_engine
from app.core.health_forms import FormState
from app.core.models import (
    ActivityLogEntry,
    CheckIn,
    CheckInMethod,
    ChosenBy,
    Customer,
    DeviceSession,
    HealthForm,
    Plan,
    PlanChoice,
    Price,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.plans import PriceNotSetError, covering_choice, end_month

# Midday on 15 November 2026, UTC (14:00 in Israel).
START = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
THIS_MONTH = Month(2026, 11)
EARLY_MONTH = Month(2026, 1)
FAKE_PDF = b"%PDF-1.4 made up"


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(checkins, "utc_now", clock)
    monkeypatch.setattr(months, "utc_now", clock)
    return clock


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def customer(db: Session) -> Customer:
    return add_customer(db, "+972501234567", date(1990, 5, 1))


@pytest.fixture
def phone(db: Session, customer: Customer) -> DeviceSession:
    return add_phone(db, customer, "a")


@pytest.fixture
def valid_form(db: Session, customer: Customer) -> None:
    add_form(db, customer, signed_on=date(2026, 3, 1))


@pytest.fixture
def prices(db: Session) -> None:
    """Every price, set from before this month."""
    amounts = {Plan.MONTHLY: 25000, Plan.TRI_MONTHLY: 65000, Plan.SINGLE_ENTRY: 4000}
    for plan, amount in amounts.items():
        add_price(db, plan, amount)


def add_customer(db: Session, number: str, born: date) -> Customer:
    customer = Customer(
        first_name="Noa", last_name="Levi", phone=number, date_of_birth=born
    )
    db.add(customer)
    db.flush()
    return customer


def add_phone(db: Session, customer: Customer, hash_letter: str) -> DeviceSession:
    device = DeviceSession(
        customer_id=customer.id,
        token_hash=hash_letter * 64,
        created_at=START - timedelta(days=30),
        last_seen_at=START - timedelta(days=30),
    )
    db.add(device)
    db.flush()
    return device


def add_form(
    db: Session,
    customer: Customer,
    *,
    signed_on: date,
    expires_on: date | None = None,
    needs_doctor_note: bool = False,
) -> None:
    db.add(
        HealthForm(
            customer_id=customer.id,
            form_version="test",
            answers_json="{}",
            needs_doctor_note=needs_doctor_note,
            signer_name="Noa Levi",
            signed_by_guardian=False,
            signed_on=signed_on,
            expires_on=expires_on or signed_on.replace(year=signed_on.year + 1),
            document=FAKE_PDF,
        )
    )
    db.flush()


def add_price(
    db: Session,
    plan: Plan,
    amount: int,
    month: Month = EARLY_MONTH,
) -> None:
    db.add(Price(plan=plan, amount_agorot=amount, valid_from_month=month))
    db.flush()


def add_choice(db: Session, customer: Customer, plan: Plan, start: Month) -> PlanChoice:
    choice = PlanChoice(
        customer_id=customer.id,
        plan=plan,
        start_month=start,
        end_month=end_month(plan, start),
        unit_price_agorot=25000,
        chosen_by=ChosenBy.CUSTOMER,
    )
    db.add(choice)
    db.flush()
    return choice


def recorded(db: Session) -> list[CheckIn]:
    return list(db.scalars(select(CheckIn).order_by(CheckIn.id)))


def choices(db: Session) -> list[PlanChoice]:
    return list(db.scalars(select(PlanChoice).order_by(PlanChoice.id)))


# Checking in


def test_a_covered_month_checks_in_and_records_the_phone(
    db: Session, customer: Customer, phone: DeviceSession, valid_form: None
) -> None:
    plan = add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)

    result = check_in_by_phone(db, phone)

    assert result.outcome is Outcome.CHECKED_IN
    assert result.plan == plan
    [row] = recorded(db)
    assert row == result.check_in
    assert row.customer_id == customer.id
    assert row.method is CheckInMethod.PHONE
    assert row.device_session_id == phone.id
    assert row.staff_user_id is None
    assert row.checked_in_at == START


def test_a_check_in_counts_as_using_the_phone(
    db: Session, customer: Customer, phone: DeviceSession, valid_form: None
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)

    check_in_by_phone(db, phone)

    assert phone.last_seen_at == START


def test_a_tri_monthly_period_from_an_earlier_month_covers(
    db: Session, customer: Customer, phone: DeviceSession, valid_form: None
) -> None:
    period = add_choice(db, customer, Plan.TRI_MONTHLY, Month(2026, 10))

    result = check_in_by_phone(db, phone)

    assert result.plan == period
    assert choices(db) == [period]


def test_a_check_in_is_not_logged(
    db: Session, customer: Customer, phone: DeviceSession, valid_form: None
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)

    check_in_by_phone(db, phone)

    assert db.scalars(select(ActivityLogEntry)).all() == []


# The health form comes first


def test_no_form_refuses_and_records_nothing(
    db: Session, customer: Customer, phone: DeviceSession
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)

    with pytest.raises(HealthFormRequiredError) as refused:
        check_in_by_phone(db, phone)

    assert refused.value.status.state is FormState.MISSING
    assert recorded(db) == []
    assert phone.last_seen_at == START - timedelta(days=30)


def test_an_expired_form_refuses(
    db: Session, customer: Customer, phone: DeviceSession
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    add_form(db, customer, signed_on=date(2025, 11, 14), expires_on=date(2026, 11, 14))

    with pytest.raises(HealthFormRequiredError) as refused:
        check_in_by_phone(db, phone)
    assert refused.value.status.state is FormState.MISSING


def test_a_form_on_its_last_day_still_counts(
    db: Session, customer: Customer, phone: DeviceSession
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    add_form(db, customer, signed_on=date(2025, 11, 16), expires_on=date(2026, 11, 15))

    assert check_in_by_phone(db, phone).outcome is Outcome.CHECKED_IN


def test_the_forms_day_is_israels_not_utcs(
    db: Session, customer: Customer, phone: DeviceSession, clock: Clock
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    add_form(db, customer, signed_on=date(2025, 11, 16), expires_on=date(2026, 11, 15))
    # 22:30 UTC on 15 November is already the 16th in Israel.
    clock.now = datetime(2026, 11, 15, 22, 30, tzinfo=UTC)

    with pytest.raises(HealthFormRequiredError):
        check_in_by_phone(db, phone)


def test_a_form_waiting_for_a_doctors_note_refuses(
    db: Session, customer: Customer, phone: DeviceSession
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    add_form(db, customer, signed_on=date(2026, 11, 1), needs_doctor_note=True)

    with pytest.raises(HealthFormRequiredError) as refused:
        check_in_by_phone(db, phone)
    assert refused.value.status.state is FormState.NEEDS_DOCTOR_NOTE


def test_the_form_is_checked_before_the_plan(
    db: Session, phone: DeviceSession, prices: None
) -> None:
    # No form and no plan: the form is what the phone must show first, and
    # a plan sent along is not chosen.
    with pytest.raises(HealthFormRequiredError):
        check_in_by_phone(db, phone, Plan.MONTHLY)
    assert choices(db) == []


def test_an_inactive_customer_is_refused(
    db: Session, customer: Customer, phone: DeviceSession, valid_form: None
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    customer.active = False
    db.flush()

    with pytest.raises(CustomerInactiveError):
        check_in_by_phone(db, phone)
    assert recorded(db) == []


# The repeat window


def test_a_check_in_within_ten_minutes_is_already_checked_in(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    clock: Clock,
) -> None:
    plan = add_choice(db, customer, Plan.SINGLE_ENTRY, THIS_MONTH)
    first = check_in_by_phone(db, phone)
    clock.advance(REPEAT_WINDOW - timedelta(seconds=1))

    again = check_in_by_phone(db, phone)

    assert again.outcome is Outcome.ALREADY_CHECKED_IN
    assert again.check_in == first.check_in
    assert again.plan == plan
    assert recorded(db) == [first.check_in]
    # Still counts as using the phone.
    assert phone.last_seen_at == clock.now


def test_a_check_in_ten_minutes_later_is_a_new_visit(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    clock: Clock,
) -> None:
    add_choice(db, customer, Plan.SINGLE_ENTRY, THIS_MONTH)
    check_in_by_phone(db, phone)
    clock.advance(REPEAT_WINDOW)

    again = check_in_by_phone(db, phone)

    assert again.outcome is Outcome.CHECKED_IN
    assert len(recorded(db)) == 2


def test_the_repeat_window_counts_the_customers_other_phones(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    clock: Clock,
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    check_in_by_phone(db, phone)
    other_phone = add_phone(db, customer, "b")
    clock.advance(timedelta(minutes=2))

    again = check_in_by_phone(db, other_phone)

    assert again.outcome is Outcome.ALREADY_CHECKED_IN
    assert len(recorded(db)) == 1


def test_another_customers_check_in_is_not_a_repeat(
    db: Session, customer: Customer, phone: DeviceSession, valid_form: None
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    other = add_customer(db, "+972507654321", date(1985, 1, 1))
    add_form(db, other, signed_on=date(2026, 3, 1))
    add_choice(db, other, Plan.MONTHLY, THIS_MONTH)
    check_in_by_phone(db, add_phone(db, other, "b"))

    assert check_in_by_phone(db, phone).outcome is Outcome.CHECKED_IN


def test_a_repeat_comes_before_the_plan_check(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    clock: Clock,
) -> None:
    # The manager cleared the plan after the check-in: a repeat is still
    # just "already checked in", with no plan to show.
    choice = add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    check_in_by_phone(db, phone)
    db.add(
        PlanChoice(
            customer_id=customer.id,
            plan=None,
            start_month=THIS_MONTH,
            end_month=THIS_MONTH,
            chosen_by=ChosenBy.CUSTOMER,
            replaces_id=choice.id,
        )
    )
    db.flush()
    clock.advance(timedelta(minutes=1))

    again = check_in_by_phone(db, phone)

    assert again.outcome is Outcome.ALREADY_CHECKED_IN
    assert again.plan is None


# The plan for the month


def test_no_plan_asks_for_one_with_the_prices(
    db: Session, phone: DeviceSession, valid_form: None, prices: None
) -> None:
    with pytest.raises(PlanRequiredError) as refused:
        check_in_by_phone(db, phone)

    assert refused.value.month == THIS_MONTH
    assert [
        (o.plan, o.price and o.price.amount_agorot) for o in refused.value.options
    ] == [
        (Plan.MONTHLY, 25000),
        (Plan.TRI_MONTHLY, 65000),
        (Plan.SINGLE_ENTRY, 4000),
    ]
    assert recorded(db) == []
    assert choices(db) == []


def test_an_under_18_customer_is_offered_the_same_prices(
    db: Session, prices: None
) -> None:
    young = add_customer(db, "+972507654321", date(2010, 1, 1))
    add_form(db, young, signed_on=date(2026, 3, 1))

    with pytest.raises(PlanRequiredError) as refused:
        check_in_by_phone(db, add_phone(db, young, "b"))
    assert [o.price and o.price.amount_agorot for o in refused.value.options] == [
        25000,
        65000,
        4000,
    ]


def test_a_plan_without_a_price_is_offered_as_not_set(
    db: Session, phone: DeviceSession, valid_form: None
) -> None:
    add_price(db, Plan.MONTHLY, 25000)

    with pytest.raises(PlanRequiredError) as refused:
        check_in_by_phone(db, phone)
    assert [o.price is not None for o in refused.value.options] == [
        True,
        False,
        False,
    ]


@pytest.mark.parametrize("plan", list(Plan))
def test_choosing_a_plan_checks_in_with_it(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
    plan: Plan,
) -> None:
    result = check_in_by_phone(db, phone, plan)

    assert result.outcome is Outcome.CHECKED_IN
    [choice] = choices(db)
    assert result.plan == choice
    assert choice.plan is plan
    assert choice.start_month == THIS_MONTH
    assert choice.chosen_by is ChosenBy.CUSTOMER
    assert choice.staff_user_id is None
    assert len(recorded(db)) == 1


def test_a_plan_sent_for_a_covered_month_is_ignored(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
) -> None:
    # The manager (or another phone) chose while the plan page was open.
    existing = add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)

    result = check_in_by_phone(db, phone, Plan.SINGLE_ENTRY)

    assert result.outcome is Outcome.CHECKED_IN
    assert result.plan == existing
    assert choices(db) == [existing]


def test_a_plan_without_a_price_refuses_and_records_nothing(
    db: Session, phone: DeviceSession, valid_form: None
) -> None:
    add_price(db, Plan.MONTHLY, 25000)

    with pytest.raises(PriceNotSetError):
        check_in_by_phone(db, phone, Plan.SINGLE_ENTRY)
    assert choices(db) == []
    assert recorded(db) == []


def test_the_month_is_israels_not_utcs(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
    clock: Clock,
) -> None:
    # November is covered, but 22:30 UTC on 30 November is already
    # December in Israel, which isn't.
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    clock.now = datetime(2026, 11, 30, 22, 30, tzinfo=UTC)

    with pytest.raises(PlanRequiredError) as refused:
        check_in_by_phone(db, phone)
    assert refused.value.month == Month(2026, 12)

    result = check_in_by_phone(db, phone, Plan.MONTHLY)
    assert result.plan is not None
    assert result.plan.start_month == Month(2026, 12)


def test_the_first_check_in_of_a_new_month_asks_again(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
    clock: Clock,
) -> None:
    check_in_by_phone(db, phone, Plan.MONTHLY)
    clock.now = datetime(2026, 12, 2, 12, 0, tzinfo=UTC)

    with pytest.raises(PlanRequiredError):
        check_in_by_phone(db, phone)


# Midnight at the end of a month


def test_a_late_visit_does_not_swallow_the_first_of_the_month(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
    clock: Clock,
) -> None:
    # 23:55 on 30 November in Israel, then 00:03 on 1 December: within ten
    # minutes, but December's first visit still gets its plan page.
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    clock.now = datetime(2026, 11, 30, 21, 55, tzinfo=UTC)
    check_in_by_phone(db, phone)
    clock.advance(timedelta(minutes=8))

    with pytest.raises(PlanRequiredError) as refused:
        check_in_by_phone(db, phone)
    assert refused.value.month == Month(2026, 12)

    december = check_in_by_phone(db, phone, Plan.MONTHLY)
    assert december.outcome is Outcome.CHECKED_IN
    assert len(recorded(db)) == 2


def test_a_repeat_just_after_midnight_on_the_first_is_still_a_repeat(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
    clock: Clock,
) -> None:
    clock.now = datetime(2026, 11, 30, 22, 1, tzinfo=UTC)  # 00:01 on 1 December
    check_in_by_phone(db, phone, Plan.MONTHLY)
    clock.advance(timedelta(minutes=3))

    assert check_in_by_phone(db, phone).outcome is Outcome.ALREADY_CHECKED_IN


def test_the_plan_is_chosen_for_the_check_ins_own_month(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    valid_form: None,
    prices: None,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The check-in reads the clock just before midnight; anything reading it
    # again would already see December. The choice must still be November's.
    clock.now = datetime(2026, 11, 30, 21, 59, 59, 999999, tzinfo=UTC)
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 11, 30, 22, 0, tzinfo=UTC)
    )

    result = check_in_by_phone(db, phone, Plan.MONTHLY)

    assert result.plan is not None
    assert result.plan.start_month == THIS_MONTH
    assert covering_choice(db, customer, THIS_MONTH) == result.plan


# Manual check-in at the desk (decision 0017)

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


def add_staff(db: Session, name: str, role: Role) -> StaffUser:
    member = StaffUser(display_name=name, role=role, pin_hash=FAKE_PIN_HASH)
    db.add(member)
    db.flush()
    return member


@pytest.fixture
def manager(db: Session) -> StaffUser:
    return add_staff(db, "Dana", Role.MANAGER)


@pytest.fixture
def instructor(db: Session) -> StaffUser:
    return add_staff(db, "Yoni", Role.INSTRUCTOR)


def logged(db: Session) -> list[ActivityLogEntry]:
    return list(db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id)))


def test_a_manual_check_in_records_and_logs_the_staff_member(
    db: Session, customer: Customer, instructor: StaffUser, valid_form: None
) -> None:
    plan = add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)

    result = check_in_manually(db, customer, by=instructor)

    assert result.outcome is Outcome.CHECKED_IN
    assert result.plan == plan
    [row] = recorded(db)
    assert row == result.check_in
    assert row.method is CheckInMethod.MANUAL
    assert row.staff_user_id == instructor.id
    assert row.device_session_id is None
    assert row.checked_in_at == START
    [entry] = logged(db)
    assert entry.staff_user_id == instructor.id
    assert entry.action == Action.CHECKIN_MANUAL
    assert entry.target_type == Target.CHECKIN
    assert entry.target_id == row.id
    assert json.loads(entry.after_json or "null") == {
        "customer_id": customer.id,
        "plan_choice_id": plan.id,
    }


def test_an_instructor_with_no_plan_records_single_entry(
    db: Session,
    customer: Customer,
    instructor: StaffUser,
    valid_form: None,
    prices: None,
) -> None:
    result = check_in_manually(db, customer, by=instructor)

    [choice] = choices(db)
    assert result.plan == choice
    assert choice.plan is Plan.SINGLE_ENTRY
    assert choice.start_month == THIS_MONTH
    assert choice.chosen_by is ChosenBy.STAFF
    assert choice.staff_user_id == instructor.id
    assert choice.unit_price_agorot == 4000
    assert [entry.action for entry in logged(db)] == [
        Action.PLAN_CHOOSE,
        Action.CHECKIN_MANUAL,
    ]


def test_an_instructor_may_not_send_a_plan(
    db: Session,
    customer: Customer,
    instructor: StaffUser,
    valid_form: None,
    prices: None,
) -> None:
    with pytest.raises(PlanNotAllowedError):
        check_in_manually(db, customer, by=instructor, plan=Plan.MONTHLY)

    assert recorded(db) == []
    assert choices(db) == []
    assert logged(db) == []


def test_an_unset_single_entry_price_refuses_an_instructor(
    db: Session, customer: Customer, instructor: StaffUser, valid_form: None
) -> None:
    with pytest.raises(PriceNotSetError):
        check_in_manually(db, customer, by=instructor)

    assert recorded(db) == []
    assert logged(db) == []


def test_the_manager_with_no_plan_is_asked_for_one(
    db: Session, customer: Customer, manager: StaffUser, valid_form: None, prices: None
) -> None:
    with pytest.raises(PlanRequiredError) as refused:
        check_in_manually(db, customer, by=manager)

    assert refused.value.month == THIS_MONTH
    assert [option.plan for option in refused.value.options] == list(Plan)
    assert recorded(db) == []
    assert choices(db) == []


def test_the_manager_chooses_a_plan_with_the_check_in(
    db: Session, customer: Customer, manager: StaffUser, valid_form: None, prices: None
) -> None:
    result = check_in_manually(db, customer, by=manager, plan=Plan.MONTHLY)

    [choice] = choices(db)
    assert result.plan == choice
    assert choice.plan is Plan.MONTHLY
    assert choice.staff_user_id == manager.id
    assert [row.method for row in recorded(db)] == [CheckInMethod.MANUAL]


def test_a_plan_the_manager_sends_for_a_covered_month_is_ignored(
    db: Session, customer: Customer, manager: StaffUser, valid_form: None, prices: None
) -> None:
    plan = add_choice(db, customer, Plan.SINGLE_ENTRY, THIS_MONTH)

    result = check_in_manually(db, customer, by=manager, plan=Plan.MONTHLY)

    assert result.plan == plan
    assert choices(db) == [plan]


def test_no_form_refuses_a_manual_check_in(
    db: Session, customer: Customer, manager: StaffUser, prices: None
) -> None:
    with pytest.raises(HealthFormRequiredError) as refused:
        check_in_manually(db, customer, by=manager, plan=Plan.MONTHLY)

    assert refused.value.status.state is FormState.MISSING
    assert recorded(db) == []
    assert choices(db) == []
    assert logged(db) == []


def test_a_form_waiting_for_a_doctors_note_refuses_a_manual_check_in(
    db: Session, customer: Customer, instructor: StaffUser, prices: None
) -> None:
    add_form(db, customer, signed_on=date(2026, 3, 1), needs_doctor_note=True)

    with pytest.raises(HealthFormRequiredError) as refused:
        check_in_manually(db, customer, by=instructor)

    assert refused.value.status.state is FormState.NEEDS_DOCTOR_NOTE
    assert recorded(db) == []


def test_an_inactive_customer_is_refused_at_the_desk(
    db: Session, customer: Customer, instructor: StaffUser, valid_form: None
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    customer.active = False

    with pytest.raises(CustomerInactiveError):
        check_in_manually(db, customer, by=instructor)

    assert recorded(db) == []


def test_a_manual_check_in_after_a_phone_one_is_a_repeat(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    instructor: StaffUser,
    valid_form: None,
    clock: Clock,
) -> None:
    plan = add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    first = check_in_by_phone(db, phone).check_in
    clock.advance(timedelta(minutes=5))

    result = check_in_manually(db, customer, by=instructor)

    assert result.outcome is Outcome.ALREADY_CHECKED_IN
    assert result.check_in == first
    assert result.plan == plan
    assert recorded(db) == [first]
    assert logged(db) == []


def test_a_phone_check_in_after_a_manual_one_is_a_repeat(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    instructor: StaffUser,
    valid_form: None,
    clock: Clock,
) -> None:
    add_choice(db, customer, Plan.MONTHLY, THIS_MONTH)
    first = check_in_manually(db, customer, by=instructor).check_in
    clock.advance(timedelta(minutes=5))

    assert check_in_by_phone(db, phone).outcome is Outcome.ALREADY_CHECKED_IN
    assert recorded(db) == [first]


def test_a_repeat_at_the_desk_comes_before_the_plan(
    db: Session,
    customer: Customer,
    instructor: StaffUser,
    valid_form: None,
    prices: None,
    clock: Clock,
) -> None:
    first = check_in_manually(db, customer, by=instructor)
    clock.advance(timedelta(minutes=5))

    again = check_in_manually(db, customer, by=instructor)

    assert again.outcome is Outcome.ALREADY_CHECKED_IN
    assert len(choices(db)) == 1
    assert again.plan == first.plan


def test_the_single_entry_fallback_is_for_the_check_ins_own_month(
    db: Session,
    customer: Customer,
    instructor: StaffUser,
    valid_form: None,
    prices: None,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # As for the phone: the check-in reads the clock just before midnight,
    # and the fallback choice must still be November's.
    clock.now = datetime(2026, 11, 30, 21, 59, 59, 999999, tzinfo=UTC)
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 11, 30, 22, 0, tzinfo=UTC)
    )

    result = check_in_manually(db, customer, by=instructor)

    assert result.plan is not None
    assert result.plan.start_month == THIS_MONTH
