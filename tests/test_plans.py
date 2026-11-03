"""Plans: the age group on the 1st of the month, the plans on offer, what
covers a month, choosing, correcting and clearing a plan, and their
activity-log entries. Names and amounts are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import months
from app.core.customers import CustomerInactiveError
from app.core.db import get_engine
from app.core.models import (
    ActivityLogEntry,
    AgeGroup,
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    Price,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.plans import (
    ChoiceReplacedError,
    MonthCoveredError,
    MonthNotChoosableError,
    NoChangeError,
    NotCorrectableError,
    PriceNotSetError,
    age_group_for,
    choice_of,
    choose_plan,
    correct_plan,
    covering_choice,
    end_month,
    plan_options,
    plan_overview,
)
from app.core.prices import PriceChange, set_prices

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
THIS_MONTH = Month(2026, 11)
# Before any month a test chooses for.
EARLY_MONTH = Month(2026, 1)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    )


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    member = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH)
    db.add(member)
    db.flush()
    return member


@pytest.fixture
def adult(db: Session) -> Customer:
    return add_customer(db, "+972501234567", date(1990, 5, 1))


@pytest.fixture
def prices(db: Session) -> None:
    """Every price, set from before this month. Under-18 prices are lower."""
    amounts = {
        Plan.MONTHLY: 25000,
        Plan.TRI_MONTHLY: 65000,
        Plan.SINGLE_ENTRY: 4000,
    }
    for plan, amount in amounts.items():
        add_price(db, plan, AgeGroup.ADULT, amount)
        add_price(db, plan, AgeGroup.UNDER_18, amount - 1000)


def add_customer(db: Session, phone: str, born: date) -> Customer:
    customer = Customer(
        first_name="Noa", last_name="Levi", phone=phone, date_of_birth=born
    )
    db.add(customer)
    db.flush()
    return customer


def add_price(
    db: Session,
    plan: Plan,
    age_group: AgeGroup,
    amount: int,
    month: Month = EARLY_MONTH,
) -> None:
    # Straight in, since set_prices refuses a past month.
    db.add(
        Price(
            plan=plan, age_group=age_group, amount_agorot=amount, valid_from_month=month
        )
    )
    db.flush()


def add_choice(
    db: Session,
    customer: Customer,
    plan: Plan,
    start: Month,
    *,
    replaces: PlanChoice | None = None,
) -> PlanChoice:
    """A choice put straight in, for months ``choose_plan`` won't take."""
    choice = PlanChoice(
        customer_id=customer.id,
        plan=plan,
        start_month=start,
        end_month=end_month(plan, start),
        age_group=AgeGroup.ADULT,
        unit_price_agorot=25000,
        chosen_by=ChosenBy.CUSTOMER,
        replaces_id=None if replaces is None else replaces.id,
    )
    db.add(choice)
    db.flush()
    return choice


def offered(db: Session, customer: Customer) -> list[tuple[Plan, AgeGroup, int | None]]:
    return [
        (o.plan, o.age_group, None if o.price is None else o.price.amount_agorot)
        for o in plan_options(db, customer, THIS_MONTH)
    ]


def log_entries(db: Session) -> list[ActivityLogEntry]:
    return list(db.scalars(select(ActivityLogEntry)))


# Age group


@pytest.mark.parametrize(
    ("born", "month", "group"),
    [
        # 18 on the 1st: the adult price that whole month.
        (date(2008, 11, 1), THIS_MONTH, AgeGroup.ADULT),
        # 18 on the 2nd: under 18 until the next month.
        (date(2008, 11, 2), THIS_MONTH, AgeGroup.UNDER_18),
        (date(2008, 11, 2), Month(2026, 12), AgeGroup.ADULT),
        (date(2008, 11, 30), THIS_MONTH, AgeGroup.UNDER_18),
        (date(2008, 10, 31), THIS_MONTH, AgeGroup.ADULT),
        (date(2010, 1, 1), THIS_MONTH, AgeGroup.UNDER_18),
        (date(1990, 5, 1), THIS_MONTH, AgeGroup.ADULT),
        # Born on 29 Feb: 18 once 1 March comes, leap year or not.
        (date(2008, 2, 29), Month(2026, 2), AgeGroup.UNDER_18),
        (date(2008, 2, 29), Month(2026, 3), AgeGroup.ADULT),
    ],
)
def test_the_age_group_is_the_age_on_the_first(
    born: date, month: Month, group: AgeGroup
) -> None:
    assert age_group_for(born, month) is group


def test_tri_monthly_ends_two_months_later_across_a_year() -> None:
    assert end_month(Plan.TRI_MONTHLY, THIS_MONTH) == Month(2027, 1)
    assert end_month(Plan.MONTHLY, THIS_MONTH) == THIS_MONTH
    assert end_month(Plan.SINGLE_ENTRY, THIS_MONTH) == THIS_MONTH


# The plans on offer


def test_options_show_this_customers_prices(
    db: Session, adult: Customer, prices: None
) -> None:
    young = add_customer(db, "+972507654321", date(2010, 1, 1))

    assert offered(db, young) == [
        (Plan.MONTHLY, AgeGroup.UNDER_18, 24000),
        (Plan.TRI_MONTHLY, AgeGroup.UNDER_18, 64000),
        (Plan.SINGLE_ENTRY, AgeGroup.UNDER_18, 3000),
    ]
    assert offered(db, adult) == [
        (Plan.MONTHLY, AgeGroup.ADULT, 25000),
        (Plan.TRI_MONTHLY, AgeGroup.ADULT, 65000),
        (Plan.SINGLE_ENTRY, AgeGroup.ADULT, 4000),
    ]


def test_an_option_without_a_price_says_so(db: Session, adult: Customer) -> None:
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 25000)
    # An under-18 price doesn't stand in for an adult one.
    add_price(db, Plan.SINGLE_ENTRY, AgeGroup.UNDER_18, 3000)

    options = plan_options(db, adult, THIS_MONTH)
    assert [o.plan for o in options] == list(Plan)
    assert [o.price is not None for o in options] == [True, False, False]


# Choosing a plan


def test_choosing_copies_the_price_and_age_group(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    choice = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)

    assert choice.customer_id == adult.id
    assert choice.plan is Plan.MONTHLY
    assert (choice.start_month, choice.end_month) == (THIS_MONTH, THIS_MONTH)
    assert choice.age_group is AgeGroup.ADULT
    assert choice.unit_price_agorot == 25000
    assert choice.chosen_by is ChosenBy.STAFF
    assert choice.staff_user_id == manager.id
    assert choice.replaces_id is None
    assert covering_choice(db, adult, THIS_MONTH) == choice


def test_an_under_18_customer_gets_the_under_18_price(
    db: Session, manager: StaffUser, prices: None
) -> None:
    # Turns 18 later this month, so still under 18 for it.
    young = add_customer(db, "+972507654321", date(2008, 11, 20))

    choice = choose_plan(db, young, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)

    assert choice.age_group is AgeGroup.UNDER_18
    assert choice.unit_price_agorot == 3000


def test_the_price_in_effect_this_month_is_used(
    db: Session, manager: StaffUser, adult: Customer
) -> None:
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 20000)
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 25000, THIS_MONTH)
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 30000, Month(2026, 12))

    choice = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)

    assert choice.unit_price_agorot == 25000


def test_a_later_price_change_does_not_reach_a_choice(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    choice = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    # Even a correction for this very month.
    set_prices(
        db,
        THIS_MONTH,
        [PriceChange(Plan.MONTHLY, AgeGroup.ADULT, 27000)],
        by=manager,
    )
    db.commit()
    db.expire_all()

    assert db.get(PlanChoice, choice.id).unit_price_agorot == 25000


def test_tri_monthly_covers_its_month_and_the_next_two(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    choice = choose_plan(db, adult, Plan.TRI_MONTHLY, THIS_MONTH, by=manager)

    assert choice.end_month == Month(2027, 1)
    assert choice.unit_price_agorot == 65000
    for month in (THIS_MONTH, Month(2026, 12), Month(2027, 1)):
        assert covering_choice(db, adult, month) == choice
    for month in (Month(2026, 10), Month(2027, 2)):
        assert covering_choice(db, adult, month) is None


def test_choosing_writes_the_activity_log(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    choice = choose_plan(db, adult, Plan.TRI_MONTHLY, THIS_MONTH, by=manager)

    [entry] = log_entries(db)
    assert entry.staff_user_id == manager.id
    assert entry.action == "plan.choose"
    assert entry.target_type == "plan_choice"
    assert entry.target_id == choice.id
    assert entry.before_json is None
    assert json.loads(entry.after_json) == {
        "customer_id": adult.id,
        "plan": "tri_monthly",
        "start_month": "2026-11",
        "end_month": "2027-01",
        "age_group": "adult",
        "unit_price_agorot": 65000,
    }


@pytest.mark.parametrize("month", [Month(2026, 10), Month(2026, 12), Month(2025, 11)])
def test_only_the_current_month_can_be_chosen(
    db: Session, manager: StaffUser, adult: Customer, prices: None, month: Month
) -> None:
    with pytest.raises(MonthNotChoosableError):
        choose_plan(db, adult, Plan.MONTHLY, month, by=manager)
    assert db.scalars(select(PlanChoice)).all() == []
    assert log_entries(db) == []


def test_the_current_month_is_the_gyms_not_utcs(
    db: Session,
    manager: StaffUser,
    adult: Customer,
    prices: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 23:30 UTC on 30 November is already 1 December in Israel.
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 11, 30, 23, 30, tzinfo=UTC)
    )
    with pytest.raises(MonthNotChoosableError):
        choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    choose_plan(db, adult, Plan.MONTHLY, Month(2026, 12), by=manager)


@pytest.mark.parametrize("plan", list(Plan))
def test_a_covered_month_is_refused(
    db: Session, manager: StaffUser, adult: Customer, prices: None, plan: Plan
) -> None:
    first = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)

    with pytest.raises(MonthCoveredError) as refused:
        choose_plan(db, adult, plan, THIS_MONTH, by=manager)
    assert refused.value.choice == first
    assert len(log_entries(db)) == 1


def test_a_month_inside_an_earlier_tri_monthly_period_is_covered(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    period = add_choice(db, adult, Plan.TRI_MONTHLY, Month(2026, 10))

    with pytest.raises(MonthCoveredError) as refused:
        choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    assert refused.value.choice == period


def test_tri_monthly_is_refused_if_a_later_month_is_covered(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    january = add_choice(db, adult, Plan.MONTHLY, Month(2027, 1))

    with pytest.raises(MonthCoveredError) as refused:
        choose_plan(db, adult, Plan.TRI_MONTHLY, THIS_MONTH, by=manager)
    assert refused.value.choice == january
    # Monthly doesn't reach January.
    choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)


def test_a_replaced_choice_no_longer_covers(db: Session, adult: Customer) -> None:
    period = add_choice(db, adult, Plan.TRI_MONTHLY, Month(2026, 10))
    correction = add_choice(db, adult, Plan.MONTHLY, Month(2026, 10), replaces=period)

    assert covering_choice(db, adult, Month(2026, 10)) == correction
    assert covering_choice(db, adult, THIS_MONTH) is None


def test_another_customers_choice_does_not_count(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    other = add_customer(db, "+972507654321", date(1985, 1, 1))
    add_choice(db, other, Plan.MONTHLY, THIS_MONTH)

    assert covering_choice(db, adult, THIS_MONTH) is None
    choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)


def test_a_price_that_is_not_set_is_refused(db: Session, manager: StaffUser) -> None:
    young = add_customer(db, "+972507654321", date(2010, 1, 1))
    # Only the adult price is set.
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 25000)

    with pytest.raises(PriceNotSetError) as refused:
        choose_plan(db, young, Plan.MONTHLY, THIS_MONTH, by=manager)
    assert (refused.value.plan, refused.value.age_group) == (
        Plan.MONTHLY,
        AgeGroup.UNDER_18,
    )
    assert db.scalars(select(PlanChoice)).all() == []
    assert log_entries(db) == []


def test_a_price_starting_next_month_is_not_set_yet(
    db: Session, manager: StaffUser, adult: Customer
) -> None:
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 25000, Month(2026, 12))

    with pytest.raises(PriceNotSetError):
        choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)


def test_an_inactive_customer_is_refused(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    adult.active = False
    db.flush()

    with pytest.raises(CustomerInactiveError):
        choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    assert log_entries(db) == []


def test_a_covered_month_is_reported_before_a_missing_price(
    db: Session, manager: StaffUser, adult: Customer
) -> None:
    # No prices at all: the month being taken is the more useful answer.
    add_choice(db, adult, Plan.MONTHLY, THIS_MONTH)

    with pytest.raises(MonthCoveredError):
        choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)


# The overview


def test_the_overview_has_this_month_the_options_and_the_history(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    old = add_choice(db, adult, Plan.MONTHLY, Month(2026, 8))
    replaced = add_choice(db, adult, Plan.SINGLE_ENTRY, Month(2026, 10))
    correction = add_choice(db, adult, Plan.MONTHLY, Month(2026, 10), replaces=replaced)
    current = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)
    add_choice(
        db,
        add_customer(db, "+972507654321", date(1985, 1, 1)),
        Plan.MONTHLY,
        THIS_MONTH,
    )

    overview = plan_overview(db, adult)

    assert overview.current_month == THIS_MONTH
    assert overview.covering == current
    assert [o.plan for o in overview.options] == list(Plan)
    assert overview.history == [current, correction, replaced, old]


def test_the_overview_with_nothing_chosen(db: Session, adult: Customer) -> None:
    overview = plan_overview(db, adult)

    assert overview.covering is None
    assert all(o.price is None for o in overview.options)
    assert overview.history == []
    assert overview.replaced_by == {}


def test_the_overview_marks_replaced_choices(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    single = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)
    monthly = correct_plan(db, adult, single, Plan.MONTHLY, by=manager)
    cleared = correct_plan(db, adult, monthly, None, by=manager)

    overview = plan_overview(db, adult)

    assert overview.covering is None
    assert overview.history == [cleared, monthly, single]
    assert overview.replaced_by == {single.id: monthly.id, monthly.id: cleared.id}


# Corrections


def test_a_correction_replaces_the_choice(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    single = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)

    monthly = correct_plan(db, adult, single, Plan.MONTHLY, by=manager)

    assert monthly.replaces_id == single.id
    assert (monthly.plan, monthly.start_month, monthly.end_month) == (
        Plan.MONTHLY,
        THIS_MONTH,
        THIS_MONTH,
    )
    assert (monthly.age_group, monthly.unit_price_agorot) == (AgeGroup.ADULT, 25000)
    assert (monthly.chosen_by, monthly.staff_user_id) == (ChosenBy.STAFF, manager.id)
    assert covering_choice(db, adult, THIS_MONTH) == monthly
    # The replaced row is kept as it was.
    assert single.plan is Plan.SINGLE_ENTRY


def test_a_correction_to_tri_monthly_covers_the_next_two_months(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)

    period = correct_plan(db, adult, monthly, Plan.TRI_MONTHLY, by=manager)

    assert (period.end_month, period.unit_price_agorot) == (Month(2027, 1), 65000)
    assert covering_choice(db, adult, Month(2027, 1)) == period


def test_a_correction_from_tri_monthly_frees_the_later_months(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    period = choose_plan(db, adult, Plan.TRI_MONTHLY, THIS_MONTH, by=manager)

    correct_plan(db, adult, period, Plan.MONTHLY, by=manager)

    assert covering_choice(db, adult, Month(2026, 12)) is None
    assert covering_choice(db, adult, Month(2027, 1)) is None


def test_a_correction_uses_the_under_18_price(
    db: Session, manager: StaffUser, prices: None
) -> None:
    young = add_customer(db, "+972507654321", date(2010, 1, 1))
    single = choose_plan(db, young, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)

    monthly = correct_plan(db, young, single, Plan.MONTHLY, by=manager)

    assert (monthly.age_group, monthly.unit_price_agorot) == (AgeGroup.UNDER_18, 24000)


def test_a_correction_to_the_same_plan_takes_a_corrected_price(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    # The manager fixes this month's price after the choice was made.
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 23000, THIS_MONTH)

    repriced = correct_plan(db, adult, monthly, Plan.MONTHLY, by=manager)

    assert repriced.unit_price_agorot == 23000


def test_a_correction_that_changes_nothing_is_refused(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)

    with pytest.raises(NoChangeError):
        correct_plan(db, adult, monthly, Plan.MONTHLY, by=manager)
    assert covering_choice(db, adult, THIS_MONTH) == monthly
    assert len(log_entries(db)) == 1


def test_a_correction_writes_the_activity_log(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    single = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)

    monthly = correct_plan(db, adult, single, Plan.MONTHLY, by=manager)

    entry = log_entries(db)[-1]
    assert entry.staff_user_id == manager.id
    assert entry.action == "plan.correct"
    assert (entry.target_type, entry.target_id) == ("plan_choice", monthly.id)
    assert json.loads(entry.before_json or "") == {
        "id": single.id,
        "customer_id": adult.id,
        "plan": "single_entry",
        "start_month": "2026-11",
        "end_month": "2026-11",
        "age_group": "adult",
        "unit_price_agorot": 4000,
    }
    assert json.loads(entry.after_json or "") == {
        "customer_id": adult.id,
        "plan": "monthly",
        "start_month": "2026-11",
        "end_month": "2026-11",
        "age_group": "adult",
        "unit_price_agorot": 25000,
        "replaces_id": single.id,
    }


# Clearing


def test_clearing_leaves_the_months_without_a_plan(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    period = choose_plan(db, adult, Plan.TRI_MONTHLY, THIS_MONTH, by=manager)

    cleared = correct_plan(db, adult, period, None, by=manager)

    assert cleared.replaces_id == period.id
    assert (cleared.plan, cleared.age_group, cleared.unit_price_agorot) == (
        None,
        None,
        None,
    )
    assert (cleared.start_month, cleared.end_month) == (THIS_MONTH, Month(2027, 1))
    for month in (THIS_MONTH, Month(2026, 12), Month(2027, 1)):
        assert covering_choice(db, adult, month) is None


def test_a_cleared_month_can_be_chosen_again(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    correct_plan(db, adult, monthly, None, by=manager)

    again = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)

    assert again.replaces_id is None
    assert covering_choice(db, adult, THIS_MONTH) == again


def test_clearing_writes_the_activity_log(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)

    cleared = correct_plan(db, adult, monthly, None, by=manager)

    entry = log_entries(db)[-1]
    assert entry.action == "plan.clear"
    assert entry.target_id == cleared.id
    assert json.loads(entry.before_json or "")["plan"] == "monthly"
    assert json.loads(entry.after_json or "") == {
        "customer_id": adult.id,
        "plan": None,
        "start_month": "2026-11",
        "end_month": "2026-11",
        "age_group": None,
        "unit_price_agorot": None,
        "replaces_id": monthly.id,
    }


def test_clearing_needs_no_price(
    db: Session, manager: StaffUser, adult: Customer
) -> None:
    monthly = add_choice(db, adult, Plan.MONTHLY, THIS_MONTH)

    assert correct_plan(db, adult, monthly, None, by=manager).plan is None


# Refused corrections


@pytest.mark.parametrize("plan", [Plan.MONTHLY, None])
def test_a_replaced_choice_cannot_be_corrected_again(
    db: Session, manager: StaffUser, adult: Customer, prices: None, plan: Plan | None
) -> None:
    single = choose_plan(db, adult, Plan.SINGLE_ENTRY, THIS_MONTH, by=manager)
    tri = correct_plan(db, adult, single, Plan.TRI_MONTHLY, by=manager)

    with pytest.raises(ChoiceReplacedError) as refused:
        correct_plan(db, adult, single, plan, by=manager)
    assert refused.value.replacement == tri


def test_a_no_plan_row_cannot_be_corrected(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    cleared = correct_plan(db, adult, monthly, None, by=manager)

    for plan in (Plan.MONTHLY, None):
        with pytest.raises(NotCorrectableError):
            correct_plan(db, adult, cleared, plan, by=manager)


@pytest.mark.parametrize(
    ("plan", "start"),
    [
        (Plan.MONTHLY, Month(2026, 10)),
        # Still covering this month, but it started in October.
        (Plan.TRI_MONTHLY, Month(2026, 10)),
        (Plan.TRI_MONTHLY, Month(2026, 9)),
    ],
)
@pytest.mark.parametrize("correction", [Plan.SINGLE_ENTRY, None])
def test_a_choice_from_an_earlier_month_cannot_be_corrected(
    db: Session,
    manager: StaffUser,
    adult: Customer,
    prices: None,
    plan: Plan,
    start: Month,
    correction: Plan | None,
) -> None:
    earlier = add_choice(db, adult, plan, start)

    with pytest.raises(NotCorrectableError):
        correct_plan(db, adult, earlier, correction, by=manager)
    assert len(db.scalars(select(PlanChoice)).all()) == 1
    assert log_entries(db) == []


def test_a_correction_cannot_run_into_a_covered_month(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    december = add_choice(db, adult, Plan.MONTHLY, Month(2026, 12))

    with pytest.raises(MonthCoveredError) as refused:
        correct_plan(db, adult, monthly, Plan.TRI_MONTHLY, by=manager)
    assert refused.value.choice == december


def test_a_correction_with_no_price_is_refused(
    db: Session, manager: StaffUser, adult: Customer
) -> None:
    add_price(db, Plan.MONTHLY, AgeGroup.ADULT, 25000)
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)

    with pytest.raises(PriceNotSetError) as refused:
        correct_plan(db, adult, monthly, Plan.SINGLE_ENTRY, by=manager)
    assert refused.value.plan is Plan.SINGLE_ENTRY
    assert len(log_entries(db)) == 1


@pytest.mark.parametrize("plan", [Plan.SINGLE_ENTRY, None])
def test_an_inactive_customers_plan_cannot_be_corrected(
    db: Session, manager: StaffUser, adult: Customer, prices: None, plan: Plan | None
) -> None:
    monthly = choose_plan(db, adult, Plan.MONTHLY, THIS_MONTH, by=manager)
    adult.active = False
    db.flush()

    with pytest.raises(CustomerInactiveError):
        correct_plan(db, adult, monthly, plan, by=manager)
    assert len(log_entries(db)) == 1


def test_another_customers_choice_cannot_be_corrected(
    db: Session, manager: StaffUser, adult: Customer, prices: None
) -> None:
    other = add_customer(db, "+972507654321", date(1985, 1, 1))
    theirs = choose_plan(db, other, Plan.MONTHLY, THIS_MONTH, by=manager)

    assert choice_of(db, adult, theirs.id) is None
    assert choice_of(db, other, theirs.id) == theirs
    with pytest.raises(ValueError, match="isn't customer"):
        correct_plan(db, adult, theirs, None, by=manager)
