"""Prices: the lookup for a month, the screen's overview, adding prices, and
their activity-log entries. Amounts are made up."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import months
from app.core.db import get_engine
from app.core.models import ActivityLogEntry, AgeGroup, Plan, Price, StaffUser
from app.core.months import Month
from app.core.permissions import Role
from app.core.prices import (
    MAX_AMOUNT_AGOROT,
    MONTH_FIELD,
    InvalidPricesError,
    PriceChange,
    price_for,
    price_overview,
    set_prices,
)

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
THIS_MONTH = Month(2026, 10)
MONTHLY_ADULT = (Plan.MONTHLY, AgeGroup.ADULT)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
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


def change(amount: int, plan_and_group=MONTHLY_ADULT) -> PriceChange:
    return PriceChange(*plan_and_group, amount)


def old_row(db: Session, month: Month, amount: int, pair=MONTHLY_ADULT) -> Price:
    """A row from before today, which ``set_prices`` wouldn't add now."""
    price = Price(
        plan=pair[0], age_group=pair[1], amount_agorot=amount, valid_from_month=month
    )
    db.add(price)
    db.flush()
    return price


def amount_for(db: Session, month: Month, pair=MONTHLY_ADULT) -> int | None:
    price = price_for(db, *pair, month)
    return None if price is None else price.amount_agorot


def log(db: Session) -> list[tuple]:
    """Every log entry as (action, target id, before, after)."""
    entries = db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id))
    return [
        (
            entry.action,
            entry.target_id,
            None if entry.before_json is None else json.loads(entry.before_json),
            None if entry.after_json is None else json.loads(entry.after_json),
        )
        for entry in entries
    ]


# The lookup


def test_no_price_is_none_not_a_guess(db: Session) -> None:
    assert price_for(db, *MONTHLY_ADULT, THIS_MONTH) is None


def test_a_price_applies_from_its_month_until_the_next_change(db: Session) -> None:
    old_row(db, Month(2026, 1), 20000)
    old_row(db, Month(2026, 6), 25000)

    assert amount_for(db, Month(2025, 12)) is None
    assert amount_for(db, Month(2026, 1)) == 20000
    assert amount_for(db, Month(2026, 5)) == 20000
    assert amount_for(db, Month(2026, 6)) == 25000
    assert amount_for(db, Month(2030, 1)) == 25000


def test_the_lookup_compares_months_across_years(db: Session) -> None:
    old_row(db, Month(2025, 12), 20000)
    old_row(db, Month(2026, 2), 25000)

    assert amount_for(db, Month(2026, 1)) == 20000


def test_the_newest_row_wins_within_a_month_even_if_lower(db: Session) -> None:
    old_row(db, Month(2026, 1), 30000)
    old_row(db, Month(2026, 1), 20000)

    assert amount_for(db, Month(2026, 1)) == 20000


def test_a_later_month_wins_over_a_newer_row_for_an_earlier_month(db: Session) -> None:
    old_row(db, Month(2026, 6), 25000)
    old_row(db, Month(2026, 1), 20000)

    assert amount_for(db, Month(2026, 7)) == 25000


def test_plans_and_age_groups_dont_mix(db: Session) -> None:
    old_row(db, Month(2026, 1), 25000)
    old_row(db, Month(2026, 1), 20000, (Plan.MONTHLY, AgeGroup.UNDER_18))
    old_row(db, Month(2026, 1), 4000, (Plan.SINGLE_ENTRY, AgeGroup.ADULT))

    assert amount_for(db, THIS_MONTH) == 25000
    assert amount_for(db, THIS_MONTH, (Plan.MONTHLY, AgeGroup.UNDER_18)) == 20000
    assert amount_for(db, THIS_MONTH, (Plan.SINGLE_ENTRY, AgeGroup.ADULT)) == 4000
    assert amount_for(db, THIS_MONTH, (Plan.TRI_MONTHLY, AgeGroup.ADULT)) is None


# Adding prices


def test_this_month_applies_at_once(db: Session, manager: StaffUser) -> None:
    set_prices(db, THIS_MONTH, [change(25000)], by=manager)

    assert amount_for(db, THIS_MONTH) == 25000
    assert amount_for(db, THIS_MONTH.plus(-1)) is None


def test_a_change_never_alters_earlier_months(db: Session, manager: StaffUser) -> None:
    old_row(db, Month(2026, 1), 20000)
    set_prices(db, Month(2026, 12), [change(25000)], by=manager)

    assert amount_for(db, Month(2026, 11)) == 20000
    assert amount_for(db, Month(2026, 12)) == 25000
    assert db.scalar(select(Price).order_by(Price.id)).amount_agorot == 20000


def test_a_correction_adds_a_row_and_keeps_the_old_one(
    db: Session, manager: StaffUser
) -> None:
    set_prices(db, THIS_MONTH, [change(25000)], by=manager)
    set_prices(db, THIS_MONTH, [change(26000)], by=manager)

    assert amount_for(db, THIS_MONTH) == 26000
    assert [p.amount_agorot for p in db.scalars(select(Price).order_by(Price.id))] == [
        25000,
        26000,
    ]


def test_a_price_already_in_effect_adds_nothing(
    db: Session, manager: StaffUser
) -> None:
    set_prices(db, THIS_MONTH, [change(25000)], by=manager)
    entries = len(log(db))

    assert set_prices(db, THIS_MONTH, [change(25000)], by=manager) == []
    assert set_prices(db, THIS_MONTH.plus(2), [change(25000)], by=manager) == []
    assert db.query(Price).count() == 1
    assert len(log(db)) == entries


def test_only_the_changed_prices_of_a_save_are_added(
    db: Session, manager: StaffUser
) -> None:
    under_18 = (Plan.MONTHLY, AgeGroup.UNDER_18)
    set_prices(db, THIS_MONTH, [change(25000), change(20000, under_18)], by=manager)

    added = set_prices(
        db, THIS_MONTH.plus(1), [change(25000), change(21000, under_18)], by=manager
    )

    assert [(p.age_group, p.amount_agorot) for p in added] == [
        (AgeGroup.UNDER_18, 21000)
    ]


def test_an_upcoming_change_can_be_cancelled_with_another_row(
    db: Session, manager: StaffUser
) -> None:
    set_prices(db, THIS_MONTH, [change(25000)], by=manager)
    set_prices(db, THIS_MONTH.plus(1), [change(30000)], by=manager)
    set_prices(db, THIS_MONTH.plus(1), [change(25000)], by=manager)

    assert amount_for(db, THIS_MONTH.plus(1)) == 25000


@pytest.mark.parametrize(
    "month", [Month(2026, 9), Month(2025, 10), Month(2028, 11), Month(2036, 10)]
)
def test_months_out_of_range_are_refused(
    db: Session, manager: StaffUser, month: Month
) -> None:
    with pytest.raises(InvalidPricesError) as refused:
        set_prices(db, month, [change(25000)], by=manager)

    assert refused.value.fields == {MONTH_FIELD}
    assert db.query(Price).count() == 0


@pytest.mark.parametrize("month", [THIS_MONTH, Month(2028, 10)])
def test_the_range_includes_both_ends(
    db: Session, manager: StaffUser, month: Month
) -> None:
    assert len(set_prices(db, month, [change(25000)], by=manager)) == 1


def test_the_month_is_the_gyms_not_utcs(
    db: Session, manager: StaffUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 22:30 UTC on 31 October is already November in Israel.
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 10, 31, 22, 30, tzinfo=UTC)
    )
    with pytest.raises(InvalidPricesError):
        set_prices(db, Month(2026, 10), [change(25000)], by=manager)
    assert len(set_prices(db, Month(2026, 11), [change(25000)], by=manager)) == 1


@pytest.mark.parametrize("amount", [0, -1, MAX_AMOUNT_AGOROT + 1, True, 100.5, "100"])
def test_bad_amounts_are_refused(
    db: Session, manager: StaffUser, amount: object
) -> None:
    with pytest.raises(InvalidPricesError) as refused:
        set_prices(db, THIS_MONTH, [change(amount)], by=manager)  # type: ignore[arg-type]

    assert refused.value.fields == {"monthly.adult"}


@pytest.mark.parametrize("amount", [1, MAX_AMOUNT_AGOROT])
def test_the_amount_limits_are_allowed(
    db: Session, manager: StaffUser, amount: int
) -> None:
    assert len(set_prices(db, THIS_MONTH, [change(amount)], by=manager)) == 1


def test_two_amounts_for_one_price_are_refused(db: Session, manager: StaffUser) -> None:
    with pytest.raises(InvalidPricesError) as refused:
        set_prices(db, THIS_MONTH, [change(25000), change(26000)], by=manager)

    assert refused.value.fields == {"monthly.adult"}


def test_a_bad_save_names_everything_and_adds_nothing(
    db: Session, manager: StaffUser
) -> None:
    with pytest.raises(InvalidPricesError) as refused:
        set_prices(
            db,
            Month(2020, 1),
            [
                change(25000),
                change(0, (Plan.TRI_MONTHLY, AgeGroup.UNDER_18)),
            ],
            by=manager,
        )

    assert refused.value.fields == {MONTH_FIELD, "tri_monthly.under_18"}
    assert db.query(Price).count() == 0
    assert log(db) == []


# The activity log


def test_the_first_price_is_logged_with_no_before(
    db: Session, manager: StaffUser
) -> None:
    [price] = set_prices(db, THIS_MONTH, [change(25000)], by=manager)

    assert log(db) == [
        (
            "price.add",
            price.id,
            None,
            {
                "plan": "monthly",
                "age_group": "adult",
                "amount_agorot": 25000,
                "valid_from_month": "2026-10",
            },
        )
    ]
    assert db.scalar(select(ActivityLogEntry)).staff_user_id == manager.id


def test_a_change_logs_the_amount_it_replaces_per_row(
    db: Session, manager: StaffUser
) -> None:
    under_18 = (Plan.MONTHLY, AgeGroup.UNDER_18)
    set_prices(db, THIS_MONTH, [change(25000), change(20000, under_18)], by=manager)
    set_prices(
        db, THIS_MONTH.plus(1), [change(26000), change(21000, under_18)], by=manager
    )

    entries = log(db)
    assert len(entries) == 4
    assert entries[2][2] == {"amount_agorot": 25000}
    assert entries[3][2] == {"amount_agorot": 20000}


# The overview


def test_an_empty_table_shows_every_price_as_not_set(db: Session) -> None:
    overview = price_overview(db)

    assert overview.current_month == THIS_MONTH
    assert [(c.plan, c.age_group, c.price) for c in overview.current] == [
        (Plan.MONTHLY, AgeGroup.ADULT, None),
        (Plan.MONTHLY, AgeGroup.UNDER_18, None),
        (Plan.TRI_MONTHLY, AgeGroup.ADULT, None),
        (Plan.TRI_MONTHLY, AgeGroup.UNDER_18, None),
        (Plan.SINGLE_ENTRY, AgeGroup.ADULT, None),
        (Plan.SINGLE_ENTRY, AgeGroup.UNDER_18, None),
    ]
    assert overview.upcoming == []
    assert overview.history == []


def test_the_overview_splits_current_upcoming_and_history(
    db: Session, manager: StaffUser
) -> None:
    old = old_row(db, Month(2026, 1), 20000)
    now = old_row(db, THIS_MONTH, 25000)
    far = old_row(db, Month(2027, 3), 40000)
    typo = old_row(db, Month(2026, 12), 99000)
    fixed = old_row(db, Month(2026, 12), 30000)
    other = old_row(db, Month(2026, 12), 22000, (Plan.MONTHLY, AgeGroup.UNDER_18))

    overview = price_overview(db)

    assert overview.current[0].price is now
    assert overview.current[1].price is None
    assert overview.upcoming == [fixed, other, far]
    assert overview.history == [far, other, fixed, typo, now, old]
