"""The plan_choices table model: defaults, the checks the database itself
enforces, that rows can't be changed or deleted, that a customer-month
never has two active choices, and "no plan" rows that clear a choice.
Names and amounts are made up."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import AgeGroup, ChosenBy, Plan, PlanChoice
from app.core.months import Month

# Not a real hash; it only has to look like one to pass the CHECK.
FAKE_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as db_session:
        for phone in ("+972501234567", "+972507654321"):
            db_session.execute(
                text(
                    "INSERT INTO customers (first_name, last_name, phone,"
                    " date_of_birth, notes, created_at, active) VALUES"
                    " ('Dana', 'Levi', :phone, '1990-05-01', '',"
                    " '2026-10-30 09:00:00.000000', 1)"
                ),
                {"phone": phone},
            )
        db_session.execute(
            text(
                "INSERT INTO staff_users (display_name, role, pin_hash,"
                " failed_attempts, active, created_at) VALUES ('Noa', 'manager',"
                " :hash, 0, 1, '2026-10-30 09:00:00.000000')"
            ),
            {"hash": FAKE_HASH},
        )
        db_session.commit()
        yield db_session


def insert(db: Session, **values: object) -> int:
    """Insert a row with plain SQL, past the model's own types, the way a
    hand edit or a buggy query would. Returns its id."""
    row = {
        "customer_id": 1,
        "plan": "monthly",
        "start_month": "2026-11",
        "end_month": "2026-11",
        "age_group": "adult",
        "unit_price_agorot": 25000,
        "chosen_at": "2026-11-03 09:00:00.000000",
        "chosen_by": "staff",
        "staff_user_id": 1,
        "replaces_id": None,
        **values,
    }
    result = db.execute(
        text(
            "INSERT INTO plan_choices (customer_id, plan, start_month, end_month,"
            " age_group, unit_price_agorot, chosen_at, chosen_by, staff_user_id,"
            " replaces_id) VALUES (:customer_id, :plan, :start_month, :end_month,"
            " :age_group, :unit_price_agorot, :chosen_at, :chosen_by,"
            " :staff_user_id, :replaces_id) RETURNING id"
        ),
        row,
    )
    return result.scalar_one()


def tri_monthly(start: str, end: str, **values: object) -> dict[str, object]:
    return {"plan": "tri_monthly", "start_month": start, "end_month": end, **values}


def no_plan(replaces_id: int, **values: object) -> dict[str, object]:
    """A row clearing choice ``replaces_id`` (a November one by default)."""
    return {
        "plan": None,
        "age_group": None,
        "unit_price_agorot": None,
        "replaces_id": replaces_id,
        **values,
    }


def test_a_row_reads_back_with_its_types_and_timestamp(db: Session) -> None:
    db.add(
        PlanChoice(
            customer_id=1,
            plan=Plan.TRI_MONTHLY,
            start_month=Month(2026, 11),
            end_month=Month(2027, 1),
            age_group=AgeGroup.UNDER_18,
            unit_price_agorot=60000,
            chosen_by=ChosenBy.CUSTOMER,
        )
    )
    db.commit()
    db.expire_all()

    row = db.query(PlanChoice).one()
    assert row.plan is Plan.TRI_MONTHLY
    assert row.start_month == Month(2026, 11)
    assert row.end_month == Month(2027, 1)
    assert row.age_group is AgeGroup.UNDER_18
    assert row.chosen_by is ChosenBy.CUSTOMER
    assert row.staff_user_id is None
    assert row.replaces_id is None
    assert row.chosen_at.tzinfo is not None


@pytest.mark.parametrize(
    "good",
    [
        {"plan": "single_entry"},
        tri_monthly("2026-11", "2027-01"),
        tri_monthly("2026-12", "2027-02"),
        {"chosen_by": "customer", "staff_user_id": None},
        {"unit_price_agorot": 0},
    ],
)
def test_the_database_accepts_good_rows(db: Session, good: dict[str, object]) -> None:
    insert(db, **good)


@pytest.mark.parametrize(
    "bad",
    [
        {"customer_id": 99},
        {"plan": "weekly"},
        {"age_group": "senior"},
        {"chosen_by": "robot"},
        {"unit_price_agorot": -1},
        {"unit_price_agorot": 100.5},
        {"unit_price_agorot": "a lot"},
        {"start_month": "2026-13", "end_month": "2026-13"},
        {"start_month": "2026-11-01", "end_month": "2026-11-01"},
        {"start_month": "0999-01", "end_month": "0999-01"},
        {"start_month": "", "end_month": ""},
        # One month for monthly and single entry, three for tri-monthly.
        {"end_month": "2026-12"},
        {"plan": "single_entry", "end_month": "2027-01"},
        tri_monthly("2026-11", "2026-11"),
        tri_monthly("2026-11", "2026-12"),
        tri_monthly("2026-11", "2027-02"),
        # Who chose and the staff member named must agree.
        {"chosen_by": "staff", "staff_user_id": None},
        {"chosen_by": "customer", "staff_user_id": 1},
        {"staff_user_id": 99},
        {"replaces_id": 99},
    ],
)
def test_the_database_refuses_bad_rows(db: Session, bad: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **bad)


@pytest.mark.parametrize(
    "missing",
    [
        "customer_id",
        "plan",
        "start_month",
        "end_month",
        "age_group",
        "unit_price_agorot",
        "chosen_at",
        "chosen_by",
    ],
)
def test_every_field_but_staff_and_replaces_is_required(
    db: Session, missing: str
) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **{missing: None})


def test_a_row_cannot_replace_itself(db: Session) -> None:
    # The id is given so it can name itself. The row doesn't exist before
    # the insert, so the same-customer trigger refuses it.
    with pytest.raises(IntegrityError, match="same customer"):
        db.execute(
            text(
                "INSERT INTO plan_choices (id, customer_id, plan, start_month,"
                " end_month, age_group, unit_price_agorot, chosen_at, chosen_by,"
                " replaces_id) VALUES (1, 1, 'monthly', '2026-11', '2026-11',"
                " 'adult', 0, '2026-11-03 09:00:00.000000', 'customer', 1)"
            )
        )


def test_rows_cannot_be_updated_or_deleted(db: Session) -> None:
    choice = insert(db)
    for statement in (
        "UPDATE plan_choices SET unit_price_agorot = 1 WHERE id = :id",
        "DELETE FROM plan_choices WHERE id = :id",
    ):
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(text(statement), {"id": choice})


@pytest.mark.parametrize(
    "second",
    [
        {},
        {"plan": "single_entry"},
        # A tri-monthly period starting before, or ending after, the month.
        tri_monthly("2026-09", "2026-11"),
        tri_monthly("2026-11", "2027-01"),
    ],
)
def test_a_customer_month_has_one_active_choice(
    db: Session, second: dict[str, object]
) -> None:
    insert(db)
    with pytest.raises(IntegrityError, match="one active choice"):
        insert(db, **second)


def test_a_tri_monthly_period_blocks_its_later_months(db: Session) -> None:
    insert(db, **tri_monthly("2026-11", "2027-01"))
    with pytest.raises(IntegrityError, match="one active choice"):
        insert(db, start_month="2027-01", end_month="2027-01")


def test_months_outside_a_period_and_other_customers_are_free(db: Session) -> None:
    insert(db, **tri_monthly("2026-11", "2027-01"))
    insert(db, start_month="2026-10", end_month="2026-10")
    insert(db, start_month="2027-02", end_month="2027-02")
    insert(db, customer_id=2)
    assert db.query(PlanChoice).count() == 4


def test_a_correction_replaces_the_active_choice(db: Session) -> None:
    single = insert(db, plan="single_entry")
    monthly = insert(db, replaces_id=single)
    # The month's active choice is now the correction, so it blocks a third.
    with pytest.raises(IntegrityError, match="one active choice"):
        insert(db, plan="single_entry")
    # And a correction of the correction is fine.
    insert(db, plan="single_entry", replaces_id=monthly)


def test_a_correction_still_cannot_overlap_another_choice(db: Session) -> None:
    november = insert(db)
    insert(db, start_month="2026-12", end_month="2026-12")
    # Replacing November with a tri-monthly period would run into December.
    with pytest.raises(IntegrityError, match="one active choice"):
        insert(db, **tri_monthly("2026-11", "2027-01"), replaces_id=november)


def test_a_choice_is_replaced_at_most_once(db: Session) -> None:
    single = insert(db, plan="single_entry")
    insert(db, replaces_id=single)
    # A "no plan" row, so the overlap trigger doesn't refuse it first.
    with pytest.raises(IntegrityError, match="UNIQUE"):
        insert(db, **no_plan(single))


def test_a_correction_is_for_the_same_customer(db: Session) -> None:
    other = insert(db, customer_id=2)
    with pytest.raises(IntegrityError, match="same customer"):
        insert(db, replaces_id=other)


def test_a_correction_keeps_the_start_month(db: Session) -> None:
    november = insert(db)
    with pytest.raises(IntegrityError, match="keeps the months"):
        insert(db, start_month="2026-12", end_month="2026-12", replaces_id=november)
    with pytest.raises(IntegrityError, match="keeps the months"):
        insert(db, **tri_monthly("2026-10", "2026-12"), replaces_id=november)


# ── "No plan" rows ──────────────────────────────────────────────────────


def test_a_no_plan_row_clears_a_choice(db: Session) -> None:
    choice = insert(db)
    cleared = insert(db, **no_plan(choice))
    row = db.get(PlanChoice, cleared)
    assert row is not None
    assert row.plan is None
    assert row.age_group is None
    assert row.unit_price_agorot is None


def test_a_no_plan_row_clears_a_whole_tri_monthly_period(db: Session) -> None:
    period = insert(db, **tri_monthly("2026-11", "2027-01"))
    insert(db, **no_plan(period, end_month="2027-01"))


@pytest.mark.parametrize(
    "bad",
    [
        # Partly empty: a row has all of plan, age group and price, or none.
        {"plan": None},
        {"age_group": None},
        {"unit_price_agorot": None},
        {"plan": None, "age_group": None},
        {"plan": None, "unit_price_agorot": None},
        {"age_group": None, "unit_price_agorot": None},
        # "No plan" only ever clears an earlier choice.
        no_plan(None),  # type: ignore[arg-type]
    ],
)
def test_the_database_refuses_partial_or_unattached_no_plan_rows(
    db: Session, bad: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        insert(db, **bad)


def test_a_no_plan_row_takes_the_months_it_clears(db: Session) -> None:
    period = insert(db, **tri_monthly("2026-11", "2027-01"))
    # It ends where the period ended, not at its first month.
    with pytest.raises(IntegrityError, match="keeps the months"):
        insert(db, **no_plan(period))
    november = insert(db, customer_id=2)
    with pytest.raises(IntegrityError, match="keeps the months"):
        insert(db, **no_plan(november, customer_id=2, end_month="2026-12"))


def test_a_cleared_month_can_be_chosen_again(db: Session) -> None:
    period = insert(db, **tri_monthly("2026-11", "2027-01"))
    insert(db, **no_plan(period, end_month="2027-01"))
    # Neither the cleared period nor the "no plan" row covers November.
    insert(db)
    insert(db, start_month="2027-01", end_month="2027-01")


def test_a_cleared_choice_cannot_be_cleared_twice(db: Session) -> None:
    choice = insert(db)
    insert(db, **no_plan(choice))
    with pytest.raises(IntegrityError, match="UNIQUE"):
        insert(db, **no_plan(choice))


def test_a_no_plan_row_is_for_the_same_customer(db: Session) -> None:
    other = insert(db, customer_id=2)
    with pytest.raises(IntegrityError, match="same customer"):
        insert(db, **no_plan(other))


def test_the_triggers_exist_at_head(db: Session) -> None:
    # A migration that rebuilds the table (batch mode) drops its triggers;
    # this catches one that forgets to create them again.
    triggers = db.scalars(
        text(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'plan_choices'"
        )
    ).all()
    assert sorted(triggers) == [
        "plan_choices_no_delete",
        "plan_choices_no_overlap",
        "plan_choices_no_update",
        "plan_choices_same_customer",
        "plan_choices_same_months",
    ]
