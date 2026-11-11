"""Punch cards (decision 0042): buying one at a check-in, its expiry by the
Israel date, using an entry per visit across months, running out, one card
at a time, no plan choice or correction while one is active, what is
logged, and the customer's card history. Names and amounts are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import checkins, months, punch_cards
from app.core.activity_log import Action, Target
from app.core.checkins import (
    REPEAT_WINDOW,
    Outcome,
    PlanRequiredError,
    check_in_by_phone,
    check_in_manually,
)
from app.core.db import get_engine
from app.core.models import (
    CARD_ENTRIES,
    ActivityLogEntry,
    CheckIn,
    ChosenBy,
    Customer,
    DeviceSession,
    HealthForm,
    Plan,
    PlanChoice,
    Price,
    PunchCard,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.plans import (
    NotAChoiceError,
    PriceNotSetError,
    PunchCardActiveError,
    check_in_options,
    choose_plan,
    correct_plan,
    plan_options,
)
from app.core.punch_cards import (
    active_card,
    buy_card,
    card_history,
    expiry_for,
)

# Midday on 15 November 2026, UTC (14:00 in Israel).
START = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
THIS_MONTH = Month(2026, 11)
EARLY_MONTH = Month(2026, 1)
CARD_PRICE = 50000
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
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
    for module in (checkins, months, punch_cards):
        monkeypatch.setattr(module, "utc_now", clock)
    return clock


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def customer(db: Session) -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1990, 5, 1),
    )
    db.add(customer)
    db.flush()
    db.add(
        HealthForm(
            customer_id=customer.id,
            form_version="test",
            answers_json="{}",
            needs_doctor_note=False,
            signer_name="Noa Levi",
            signed_by_guardian=False,
            signed_on=date(2026, 3, 1),
            expires_on=date(2027, 12, 31),
            document=FAKE_PDF,
        )
    )
    db.flush()
    return customer


@pytest.fixture
def phone(db: Session, customer: Customer) -> DeviceSession:
    device = DeviceSession(
        customer_id=customer.id,
        token_hash="a" * 64,
        created_at=START - timedelta(days=30),
        last_seen_at=START - timedelta(days=30),
    )
    db.add(device)
    db.flush()
    return device


@pytest.fixture
def prices(db: Session) -> None:
    """Every price, the punch card's included, set from before this month."""
    amounts = {
        Plan.MONTHLY: 25000,
        Plan.TRI_MONTHLY: 65000,
        Plan.SINGLE_ENTRY: 4000,
        Plan.PUNCH_CARD: CARD_PRICE,
    }
    for plan, amount in amounts.items():
        add_price(db, plan, amount)


def add_price(db: Session, plan: Plan, amount: int, month: Month = EARLY_MONTH) -> None:
    db.add(Price(plan=plan, amount_agorot=amount, valid_from_month=month))
    db.flush()


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


def cards(db: Session) -> list[PunchCard]:
    return list(db.scalars(select(PunchCard).order_by(PunchCard.id)))


def recorded(db: Session) -> list[CheckIn]:
    return list(db.scalars(select(CheckIn).order_by(CheckIn.id)))


def choices(db: Session) -> list[PlanChoice]:
    return list(db.scalars(select(PlanChoice).order_by(PlanChoice.id)))


def logged(db: Session) -> list[ActivityLogEntry]:
    return list(db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id)))


def israel(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A winter Israel time (UTC+2) as UTC."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC) - timedelta(hours=2)


def buy_on_phone(db: Session, phone: DeviceSession) -> PunchCard:
    check_in_by_phone(db, phone, Plan.PUNCH_CARD)
    [card] = cards(db)
    return card


def later(clock: Clock) -> None:
    """Past the 10-minute repeat window."""
    clock.advance(REPEAT_WINDOW + timedelta(minutes=1))


# Expiry


@pytest.mark.parametrize(
    ("bought", "expires"),
    [
        (Month(2027, 1), date(2027, 3, 1)),
        (Month(2026, 11), date(2027, 1, 1)),
        (Month(2026, 12), date(2027, 2, 1)),
    ],
)
def test_a_card_expires_on_the_first_of_the_month_after_next(
    bought: Month, expires: date
) -> None:
    assert expiry_for(bought) == expires


# Buying on the phone


def test_buying_on_the_phone_copies_the_price_and_uses_the_first_entry(
    db: Session, customer: Customer, phone: DeviceSession, prices: None
) -> None:
    result = check_in_by_phone(db, phone, Plan.PUNCH_CARD)

    [card] = cards(db)
    assert card.customer_id == customer.id
    assert card.price_agorot == CARD_PRICE
    assert card.bought_month == THIS_MONTH
    assert card.expires_on == date(2027, 1, 1)
    assert card.bought_by is ChosenBy.CUSTOMER
    assert card.staff_user_id is None
    assert result.outcome is Outcome.CHECKED_IN
    assert result.plan is None
    assert result.card is not None
    assert result.card.card == card
    assert result.card.entries_left == CARD_ENTRIES - 1
    [row] = recorded(db)
    assert row.punch_card_id == card.id
    # Not a plan choice, and the customer's own purchase isn't logged.
    assert choices(db) == []
    assert logged(db) == []


def test_a_card_without_a_price_is_offered_as_not_set_and_refused(
    db: Session, phone: DeviceSession
) -> None:
    add_price(db, Plan.MONTHLY, 25000)

    with pytest.raises(PlanRequiredError) as refused:
        check_in_by_phone(db, phone)
    assert [(o.plan, o.price is not None) for o in refused.value.options][-1] == (
        Plan.PUNCH_CARD,
        False,
    )
    with pytest.raises(PriceNotSetError):
        check_in_by_phone(db, phone, Plan.PUNCH_CARD)
    assert cards(db) == []
    assert recorded(db) == []


def test_a_later_price_change_never_touches_a_bought_card(
    db: Session, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)
    add_price(db, Plan.PUNCH_CARD, 60000, THIS_MONTH)

    db.expire_all()
    assert card.price_agorot == CARD_PRICE


# Using a card


def test_an_active_card_pays_with_an_entry_and_no_plan_page(
    db: Session, clock: Clock, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)
    later(clock)

    result = check_in_by_phone(db, phone)

    assert result.outcome is Outcome.CHECKED_IN
    assert result.plan is None
    assert result.card is not None
    assert result.card.card == card
    assert result.card.entries_left == CARD_ENTRIES - 2
    assert [row.punch_card_id for row in recorded(db)] == [card.id, card.id]


def test_the_card_covers_the_next_month_too(
    db: Session, clock: Clock, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)
    clock.now = israel(2026, 12, 20, 10)

    result = check_in_by_phone(db, phone)

    assert result.card is not None and result.card.card == card
    assert choices(db) == []


def test_an_option_sent_while_a_card_counts_is_ignored(
    db: Session, clock: Clock, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)
    later(clock)

    # Another phone, still on the plan page, taps monthly.
    result = check_in_by_phone(db, phone, Plan.MONTHLY)

    assert result.card is not None and result.card.card == card
    assert choices(db) == []
    assert len(cards(db)) == 1


def test_a_repeat_uses_no_entry_and_shows_the_card(
    db: Session, clock: Clock, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)
    clock.advance(timedelta(minutes=5))

    result = check_in_by_phone(db, phone)

    assert result.outcome is Outcome.ALREADY_CHECKED_IN
    assert result.card is not None
    assert result.card.card == card
    assert result.card.entries_left == CARD_ENTRIES - 1
    assert len(recorded(db)) == 1


def test_a_used_up_card_shows_the_plan_page_again(
    db: Session, clock: Clock, phone: DeviceSession, prices: None
) -> None:
    buy_on_phone(db, phone)
    for _ in range(CARD_ENTRIES - 1):
        later(clock)
        result = check_in_by_phone(db, phone)
    assert result.card is not None and result.card.entries_left == 0
    later(clock)

    with pytest.raises(PlanRequiredError):
        check_in_by_phone(db, phone)
    # A new card can be bought now.
    result = check_in_by_phone(db, phone, Plan.PUNCH_CARD)
    assert len(cards(db)) == 2
    assert result.card is not None and result.card.entries_left == CARD_ENTRIES - 1


def test_the_card_expires_at_midnight_israel_time(
    db: Session, clock: Clock, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)
    # 23:30 on 31 December in Israel, 21:30 UTC: still valid.
    clock.now = israel(2026, 12, 31, 23, 30)
    result = check_in_by_phone(db, phone)
    assert result.card is not None and result.card.card == card

    # 00:30 on 1 January in Israel, still 31 December in UTC: expired.
    clock.now = israel(2027, 1, 1, 0, 30)
    with pytest.raises(PlanRequiredError):
        check_in_by_phone(db, phone)
    assert active_card(db, phone.customer, date(2027, 1, 1)) is None


# At the desk


def test_an_instructor_uses_an_active_card_not_single_entry(
    db: Session,
    clock: Clock,
    customer: Customer,
    phone: DeviceSession,
    instructor: StaffUser,
    prices: None,
) -> None:
    card = buy_on_phone(db, phone)
    later(clock)

    result = check_in_manually(db, customer, by=instructor)

    assert result.plan is None
    assert result.card is not None and result.card.card == card
    assert result.card.entries_left == CARD_ENTRIES - 2
    assert choices(db) == []
    [entry] = logged(db)
    assert entry.action == Action.CHECKIN_MANUAL
    assert json.loads(entry.after_json or "null") == {
        "customer_id": customer.id,
        "plan_choice_id": None,
        "punch_card_id": card.id,
    }


def test_an_instructor_without_a_card_still_gets_single_entry(
    db: Session, customer: Customer, instructor: StaffUser, prices: None
) -> None:
    result = check_in_manually(db, customer, by=instructor)

    assert result.card is None
    assert result.plan is not None and result.plan.plan is Plan.SINGLE_ENTRY
    assert cards(db) == []


def test_the_manager_sells_a_card_at_the_desk_and_it_is_logged(
    db: Session, customer: Customer, manager: StaffUser, prices: None
) -> None:
    with pytest.raises(PlanRequiredError) as refused:
        check_in_manually(db, customer, by=manager)
    assert refused.value.options[-1].plan is Plan.PUNCH_CARD

    result = check_in_manually(db, customer, by=manager, plan=Plan.PUNCH_CARD)

    [card] = cards(db)
    assert card.bought_by is ChosenBy.STAFF
    assert card.staff_user_id == manager.id
    assert result.card is not None and result.card.entries_left == CARD_ENTRIES - 1
    [bought, checked_in] = logged(db)
    assert bought.staff_user_id == manager.id
    assert bought.action == Action.PUNCH_CARD_BUY
    assert bought.target_type == Target.PUNCH_CARD
    assert bought.target_id == card.id
    assert json.loads(bought.after_json or "null") == {
        "customer_id": customer.id,
        "price_agorot": CARD_PRICE,
        "bought_month": "2026-11",
        "expires_on": "2027-01-01",
    }
    assert checked_in.action == Action.CHECKIN_MANUAL


# One card at a time, never alongside a plan


def test_no_second_card_while_one_is_active(
    db: Session, customer: Customer, phone: DeviceSession, prices: None
) -> None:
    card = buy_on_phone(db, phone)

    with pytest.raises(PunchCardActiveError) as refused:
        buy_card(db, customer, THIS_MONTH, date(2026, 11, 15), by=None)
    assert refused.value.card == card
    assert len(cards(db)) == 1


@pytest.mark.parametrize("plan", [Plan.MONTHLY, Plan.TRI_MONTHLY, Plan.SINGLE_ENTRY])
def test_no_plan_is_chosen_while_a_card_is_active(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    manager: StaffUser,
    prices: None,
    plan: Plan,
) -> None:
    card = buy_on_phone(db, phone)

    with pytest.raises(PunchCardActiveError) as refused:
        choose_plan(db, customer, plan, THIS_MONTH, by=manager)
    assert refused.value.card == card
    assert choices(db) == []


@pytest.mark.parametrize("correction", [Plan.MONTHLY, None])
def test_no_correction_or_clearing_while_a_card_is_active(
    db: Session,
    customer: Customer,
    phone: DeviceSession,
    manager: StaffUser,
    prices: None,
    correction: Plan | None,
) -> None:
    # A choice this month that a card came after cannot happen through the
    # app (a covered month never buys a card); written directly here.
    choice = PlanChoice(
        customer_id=customer.id,
        plan=Plan.SINGLE_ENTRY,
        start_month=THIS_MONTH,
        end_month=THIS_MONTH,
        unit_price_agorot=4000,
        chosen_by=ChosenBy.CUSTOMER,
    )
    db.add(choice)
    db.flush()
    buy_card(db, customer, THIS_MONTH, date(2026, 11, 15), by=None)

    with pytest.raises(PunchCardActiveError):
        correct_plan(db, customer, choice, correction, by=manager)
    assert choices(db) == [choice]


def test_choosing_works_again_once_the_card_runs_out(
    db: Session,
    clock: Clock,
    customer: Customer,
    phone: DeviceSession,
    manager: StaffUser,
    prices: None,
) -> None:
    buy_on_phone(db, phone)
    for _ in range(CARD_ENTRIES - 1):
        later(clock)
        check_in_by_phone(db, phone)

    choice = choose_plan(db, customer, Plan.MONTHLY, THIS_MONTH, by=manager)
    assert choice.plan is Plan.MONTHLY


def test_a_punch_card_is_never_a_plan_choice(
    db: Session, customer: Customer, manager: StaffUser, prices: None
) -> None:
    with pytest.raises(NotAChoiceError):
        choose_plan(db, customer, Plan.PUNCH_CARD, THIS_MONTH, by=manager)
    choice = choose_plan(db, customer, Plan.MONTHLY, THIS_MONTH, by=manager)
    with pytest.raises(NotAChoiceError):
        correct_plan(db, customer, choice, Plan.PUNCH_CARD, by=manager)
    assert cards(db) == []


def test_only_check_in_offers_the_card(db: Session, prices: None) -> None:
    assert [o.plan for o in check_in_options(db, THIS_MONTH)] == list(Plan)
    assert Plan.PUNCH_CARD not in [o.plan for o in plan_options(db, THIS_MONTH)]


# History


def test_the_history_lists_every_card_newest_first_with_its_entries(
    db: Session,
    clock: Clock,
    customer: Customer,
    phone: DeviceSession,
    manager: StaffUser,
    prices: None,
) -> None:
    assert card_history(db, customer) == []
    first = buy_on_phone(db, phone)
    later(clock)
    check_in_by_phone(db, phone)
    # It expires; the manager sells the next one in January.
    clock.now = israel(2027, 1, 10, 10)
    check_in_manually(db, customer, by=manager, plan=Plan.PUNCH_CARD)
    second = cards(db)[-1]

    history = card_history(db, customer)

    assert [(b.card, b.entries_used) for b in history] == [(second, 1), (first, 2)]
    assert history[0].card.staff == manager
    current = active_card(db, customer, date(2027, 1, 10))
    assert current is not None and current.card == second
