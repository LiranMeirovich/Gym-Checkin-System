"""The monthly report's calculation (design doc: "Monthly report"; decisions
0042, 0043): each plan, tri-monthly's three months, punch cards in the month
bought and the next, a card running out mid-month, corrections, the
Israel-local month boundary, and the same answer every time. The history
is written straight into the tables. Names and amounts are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from itertools import count
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import (
    CARD_ENTRIES,
    CheckIn,
    CheckInMethod,
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    Price,
    PunchCard,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.punch_cards import expiry_for
from app.core.reports import MonthReport, ReportRow, calculate

OCT = Month(2026, 10)
NOV = Month(2026, 11)
DEC = Month(2026, 12)
JAN = Month(2027, 1)
MONTHLY = 25000
TRI_MONTHLY = 65000
SINGLE = 4000
CARD = 50000
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"

_phones = count(1234567)


def at(month: Month, day: int, hour: int = 12) -> datetime:
    """Midday UTC (14:00 in Israel in winter) on ``day`` of ``month``."""
    return datetime(month.year, month.month, day, hour, tzinfo=UTC)


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def staff(db: Session) -> StaffUser:
    member = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH)
    db.add(member)
    db.flush()
    return member


def add_customer(db: Session, first: str = "Noa", last: str = "Levi") -> Customer:
    customer = Customer(
        first_name=first,
        last_name=last,
        phone=f"+97250{next(_phones)}",
        date_of_birth=date(1990, 5, 1),
    )
    db.add(customer)
    db.flush()
    return customer


def choose(
    db: Session,
    customer: Customer,
    plan: Plan | None,
    start: Month,
    price: int | None,
    *,
    when: datetime | None = None,
    replaces: PlanChoice | None = None,
) -> PlanChoice:
    end = start.plus(2) if plan is Plan.TRI_MONTHLY else start
    choice = PlanChoice(
        customer_id=customer.id,
        plan=plan,
        start_month=start,
        end_month=replaces.end_month if replaces is not None else end,
        unit_price_agorot=price,
        chosen_at=when or at(start, 1),
        chosen_by=ChosenBy.CUSTOMER,
        replaces_id=None if replaces is None else replaces.id,
    )
    db.add(choice)
    db.flush()
    return choice


def buy(
    db: Session, customer: Customer, month: Month, *, day: int = 1, price: int = CARD
) -> PunchCard:
    card = PunchCard(
        customer_id=customer.id,
        price_agorot=price,
        bought_month=month,
        expires_on=expiry_for(month),
        bought_at=at(month, day),
        bought_by=ChosenBy.CUSTOMER,
    )
    db.add(card)
    db.flush()
    return card


def visit(
    db: Session,
    customer: Customer,
    staff: StaffUser,
    when: datetime,
    card: PunchCard | None = None,
) -> None:
    db.add(
        CheckIn(
            customer_id=customer.id,
            checked_in_at=when,
            method=CheckInMethod.MANUAL,
            staff_user_id=staff.id,
            punch_card_id=None if card is None else card.id,
        )
    )
    db.flush()


def use_up(
    db: Session, customer: Customer, staff: StaffUser, card: PunchCard, month: Month
) -> None:
    """All of ``card``'s entries, one a minute from midday on ``month``'s
    2nd."""
    for minute in range(CARD_ENTRIES):
        visit(db, customer, staff, at(month, 2) + timedelta(minutes=minute), card)


def only_row(report: MonthReport) -> ReportRow:
    assert len(report.rows) == 1
    return report.rows[0]


# --- Each plan -----------------------------------------------------------


def test_monthly_pays_its_price_and_ends_on_the_months_last_day(db: Session) -> None:
    noa = add_customer(db)
    choose(db, noa, Plan.MONTHLY, NOV, MONTHLY)

    row = only_row(calculate(db, NOV))

    assert row == ReportRow(
        customer_id=noa.id,
        first_name="Noa",
        last_name="Levi",
        plans=(Plan.MONTHLY,),
        payment_agorot=MONTHLY,
        ends_on=date(2026, 11, 30),
    )


def test_monthly_is_charged_without_any_visit(db: Session) -> None:
    choose(db, add_customer(db), Plan.MONTHLY, NOV, MONTHLY)

    assert only_row(calculate(db, NOV)).payment_agorot == MONTHLY


def test_tri_monthly_is_paid_in_its_first_month_and_zero_in_the_next_two(
    db: Session,
) -> None:
    choose(db, add_customer(db), Plan.TRI_MONTHLY, NOV, TRI_MONTHLY)

    payments = [only_row(calculate(db, m)).payment_agorot for m in (NOV, DEC, JAN)]

    assert payments == [TRI_MONTHLY, 0, 0]
    for month in (NOV, DEC, JAN):
        assert only_row(calculate(db, month)).ends_on == date(2027, 1, 31)
        assert only_row(calculate(db, month)).plans == (Plan.TRI_MONTHLY,)
    assert calculate(db, OCT).rows == ()
    assert calculate(db, Month(2027, 2)).rows == ()


def test_single_entry_charges_each_visit_in_the_month(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    choose(db, noa, Plan.SINGLE_ENTRY, NOV, SINGLE)
    for day in (3, 10, 24):
        visit(db, noa, staff, at(NOV, day))
    visit(db, noa, staff, at(OCT, 20))
    visit(db, noa, staff, at(DEC, 2))

    row = only_row(calculate(db, NOV))

    assert row.payment_agorot == 3 * SINGLE
    assert row.ends_on is None
    assert row.plans == (Plan.SINGLE_ENTRY,)


def test_single_entry_without_visits_shows_zero(db: Session) -> None:
    choose(db, add_customer(db), Plan.SINGLE_ENTRY, NOV, SINGLE)

    assert only_row(calculate(db, NOV)).payment_agorot == 0


def test_the_month_starts_at_israel_midnight_not_utc(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    choose(db, noa, Plan.SINGLE_ENTRY, OCT, SINGLE)
    choose(db, noa, Plan.SINGLE_ENTRY, NOV, SINGLE)
    # 22:30 UTC on 31 October is 00:30 on 1 November in Israel (UTC+2).
    visit(db, noa, staff, datetime(2026, 10, 31, 22, 30, tzinfo=UTC))
    # 21:30 UTC on 31 October is 23:30 the same day in Israel.
    visit(db, noa, staff, datetime(2026, 10, 31, 21, 30, tzinfo=UTC))

    assert only_row(calculate(db, OCT)).payment_agorot == SINGLE
    assert only_row(calculate(db, NOV)).payment_agorot == SINGLE


def test_the_price_on_the_choice_is_charged_not_the_price_table(db: Session) -> None:
    choose(db, add_customer(db), Plan.MONTHLY, NOV, MONTHLY)
    db.add(Price(plan=Plan.MONTHLY, amount_agorot=99900, valid_from_month=NOV))
    db.flush()

    assert only_row(calculate(db, NOV)).payment_agorot == MONTHLY


# --- Punch cards ---------------------------------------------------------


def test_a_card_is_paid_in_the_month_it_was_bought_ending_on_its_last_valid_day(
    db: Session,
) -> None:
    noa = add_customer(db)
    buy(db, noa, NOV, day=28)

    row = only_row(calculate(db, NOV))

    assert row.plans == (Plan.PUNCH_CARD,)
    assert row.payment_agorot == CARD
    assert row.ends_on == date(2026, 12, 31)


def test_a_card_with_entries_left_shows_zero_the_next_month(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    card = buy(db, noa, NOV)
    visit(db, noa, staff, at(NOV, 5), card)

    row = only_row(calculate(db, DEC))

    assert (row.plans, row.payment_agorot, row.ends_on) == (
        (Plan.PUNCH_CARD,),
        0,
        date(2026, 12, 31),
    )
    assert calculate(db, JAN).rows == ()


def test_a_card_used_up_last_month_has_no_row_this_month(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    use_up(db, noa, staff, buy(db, noa, NOV), NOV)

    assert calculate(db, DEC).rows == ()


def test_a_card_used_up_on_this_months_first_still_counts_as_covering_it(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    card = buy(db, noa, NOV)
    for minute in range(CARD_ENTRIES - 1):
        visit(db, noa, staff, at(NOV, 2) + timedelta(minutes=minute), card)
    visit(db, noa, staff, at(DEC, 1), card)

    assert only_row(calculate(db, DEC)).payment_agorot == 0


def test_card_check_ins_are_never_single_entries(db: Session, staff: StaffUser) -> None:
    noa = add_customer(db)
    card = buy(db, noa, NOV, day=1)
    use_up(db, noa, staff, card, NOV)
    choose(db, noa, Plan.SINGLE_ENTRY, NOV, SINGLE, when=at(NOV, 20))
    visit(db, noa, staff, at(NOV, 20))
    visit(db, noa, staff, at(NOV, 25))

    row = only_row(calculate(db, NOV))

    assert row.plans == (Plan.PUNCH_CARD, Plan.SINGLE_ENTRY)
    assert row.payment_agorot == CARD + 2 * SINGLE
    assert row.ends_on is None


def test_a_card_then_monthly_in_one_month_charges_both_and_ends_with_the_month(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    use_up(db, noa, staff, buy(db, noa, NOV), NOV)
    choose(db, noa, Plan.MONTHLY, NOV, MONTHLY, when=at(NOV, 20))

    row = only_row(calculate(db, NOV))

    assert row.plans == (Plan.PUNCH_CARD, Plan.MONTHLY)
    assert row.payment_agorot == CARD + MONTHLY
    assert row.ends_on == date(2026, 11, 30)


def test_last_months_card_running_out_then_a_new_card(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    old = buy(db, noa, NOV, day=20)
    for minute in range(CARD_ENTRIES):
        when = at(NOV, 25) if minute < 10 else at(DEC, 3)
        visit(db, noa, staff, when + timedelta(minutes=minute), old)
    buy(db, noa, DEC, day=10)

    row = only_row(calculate(db, DEC))

    assert row.plans == (Plan.PUNCH_CARD, Plan.PUNCH_CARD)
    assert row.payment_agorot == CARD
    assert row.ends_on == date(2027, 1, 31)


def test_the_cards_own_price_is_charged(db: Session) -> None:
    buy(db, add_customer(db), NOV, price=42000)

    assert only_row(calculate(db, NOV)).payment_agorot == 42000


# --- Corrections and who appears -----------------------------------------


def test_a_corrected_choice_charges_only_the_replacement(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    single = choose(db, noa, Plan.SINGLE_ENTRY, NOV, SINGLE)
    visit(db, noa, staff, at(NOV, 3))
    choose(db, noa, Plan.MONTHLY, NOV, MONTHLY, when=at(NOV, 4), replaces=single)

    row = only_row(calculate(db, NOV))

    assert row.plans == (Plan.MONTHLY,)
    assert row.payment_agorot == MONTHLY


def test_a_cleared_choice_has_no_row(db: Session) -> None:
    noa = add_customer(db)
    monthly = choose(db, noa, Plan.MONTHLY, NOV, MONTHLY)
    choose(db, noa, None, NOV, None, when=at(NOV, 2), replaces=monthly)

    assert calculate(db, NOV).rows == ()


def test_a_cleared_tri_monthly_covers_none_of_its_months(db: Session) -> None:
    noa = add_customer(db)
    tri = choose(db, noa, Plan.TRI_MONTHLY, NOV, TRI_MONTHLY)
    choose(db, noa, None, NOV, None, when=at(NOV, 2), replaces=tri)

    assert [calculate(db, m).rows for m in (NOV, DEC, JAN)] == [(), (), ()]


def test_customers_without_a_plan_or_card_dont_appear(
    db: Session, staff: StaffUser
) -> None:
    visit(db, add_customer(db), staff, at(NOV, 3))

    assert calculate(db, NOV).rows == ()


def test_a_deactivated_customer_still_appears_for_their_month(db: Session) -> None:
    noa = add_customer(db)
    choose(db, noa, Plan.MONTHLY, NOV, MONTHLY)
    noa.active = False
    db.flush()

    assert only_row(calculate(db, NOV)).customer_id == noa.id


# --- The whole report ----------------------------------------------------


def test_rows_are_sorted_by_last_then_first_name_and_totalled(db: Session) -> None:
    choose(db, add_customer(db, "Yossi", "Cohen"), Plan.MONTHLY, NOV, MONTHLY)
    choose(db, add_customer(db, "Avi", "Levi"), Plan.TRI_MONTHLY, NOV, TRI_MONTHLY)
    buy(db, add_customer(db, "Maya", "Katz"), NOV)
    choose(db, add_customer(db, "Dana", "Cohen"), Plan.MONTHLY, NOV, MONTHLY)

    report = calculate(db, NOV)

    names = [(row.last_name, row.first_name) for row in report.rows]
    assert names == [
        ("Cohen", "Dana"),
        ("Cohen", "Yossi"),
        ("Katz", "Maya"),
        ("Levi", "Avi"),
    ]
    assert report.total_agorot == 2 * MONTHLY + TRI_MONTHLY + CARD


def test_an_empty_month_totals_zero(db: Session) -> None:
    report = calculate(db, NOV)

    assert report == MonthReport(NOV, ())
    assert report.total_agorot == 0


def test_a_past_month_comes_out_the_same_after_later_activity(
    db: Session, staff: StaffUser
) -> None:
    noa = add_customer(db)
    choose(db, noa, Plan.SINGLE_ENTRY, NOV, SINGLE)
    visit(db, noa, staff, at(NOV, 3))
    buy(db, add_customer(db, "Maya", "Katz"), NOV)
    before = calculate(db, NOV)

    choose(db, noa, Plan.MONTHLY, DEC, MONTHLY)
    visit(db, noa, staff, at(DEC, 2))
    db.add(Price(plan=Plan.SINGLE_ENTRY, amount_agorot=1, valid_from_month=NOV))
    db.flush()

    assert calculate(db, NOV) == before
