"""allow no plan rows in plan choices: clearing a choice is a new row too.

Revision ID: 818f444bb393
Revises: 391fa9399bd0
Create Date: 2026-11-03 09:56:05.007039+00:00

A "no plan" row replaces a choice and has no plan, age group or price, so
``plan``, ``age_group`` and ``unit_price_agorot`` become nullable. A new
CHECK keeps a row either complete or a "no plan" row that clears an
earlier choice; the price CHECK and the months CHECK let a "no plan" row
through.

The table is rebuilt (batch mode) and existing rows are copied unchanged.
SQLite drops a table's triggers with it, so they're dropped first and
created again afterwards:

- ``no_update``, ``no_delete`` and ``same_customer``: unchanged.
- ``no_overlap``: a "no plan" row covers nothing, so it neither conflicts
  nor counts as covering.
- ``same_months`` (new): a correction starts in the month of the choice
  it replaces, and a "no plan" row also ends where that choice ended, so a
  correction never reaches into another month.

``downgrade()`` is a full undo while no "no plan" rows exist. With any, it
stops with an error rather than delete history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "818f444bb393"
down_revision: str | Sequence[str] | None = "391fa9399bd0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = tuple(
    f"CREATE TRIGGER plan_choices_no_{verb.lower()} BEFORE {verb} ON plan_choices"
    " BEGIN SELECT RAISE(ABORT, 'plan_choices is append-only'); END"
    for verb in ("UPDATE", "DELETE")
)

SAME_CUSTOMER = (
    "CREATE TRIGGER plan_choices_same_customer BEFORE INSERT ON plan_choices"
    " WHEN NEW.replaces_id IS NOT NULL"
    " AND (SELECT customer_id FROM plan_choices WHERE id = NEW.replaces_id)"
    " IS NOT NEW.customer_id"
    " BEGIN SELECT RAISE(ABORT,"
    " 'plan_choices: a choice replaces one of the same customer'); END"
)

# As in 391fa9399bd0, plus: "no plan" rows (plan IS NULL) cover nothing.
NO_OVERLAP = (
    "CREATE TRIGGER plan_choices_no_overlap BEFORE INSERT ON plan_choices"
    " WHEN NEW.plan IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM plan_choices AS c"
    " WHERE c.customer_id = NEW.customer_id"
    " AND c.plan IS NOT NULL"
    " AND c.id IS NOT NEW.replaces_id"
    " AND c.start_month <= NEW.end_month"
    " AND c.end_month >= NEW.start_month"
    " AND NOT EXISTS ("
    "SELECT 1 FROM plan_choices AS r WHERE r.replaces_id = c.id))"
    " BEGIN SELECT RAISE(ABORT,"
    " 'plan_choices: a customer-month has one active choice'); END"
)

OLD_NO_OVERLAP = (
    "CREATE TRIGGER plan_choices_no_overlap BEFORE INSERT ON plan_choices"
    " WHEN EXISTS ("
    "SELECT 1 FROM plan_choices AS c"
    " WHERE c.customer_id = NEW.customer_id"
    " AND c.id IS NOT NEW.replaces_id"
    " AND c.start_month <= NEW.end_month"
    " AND c.end_month >= NEW.start_month"
    " AND NOT EXISTS ("
    "SELECT 1 FROM plan_choices AS r WHERE r.replaces_id = c.id))"
    " BEGIN SELECT RAISE(ABORT,"
    " 'plan_choices: a customer-month has one active choice'); END"
)

# "!=", not "IS NOT": a replaced id that doesn't exist gives NULL, which
# doesn't fire this, and is same_customer's (and the foreign key's) to refuse.
SAME_MONTHS = (
    "CREATE TRIGGER plan_choices_same_months BEFORE INSERT ON plan_choices"
    " WHEN NEW.replaces_id IS NOT NULL AND ("
    "(SELECT start_month FROM plan_choices WHERE id = NEW.replaces_id)"
    " != NEW.start_month"
    " OR (NEW.plan IS NULL"
    " AND (SELECT end_month FROM plan_choices WHERE id = NEW.replaces_id)"
    " != NEW.end_month))"
    " BEGIN SELECT RAISE(ABORT,"
    " 'plan_choices: a correction keeps the months of the choice it replaces');"
    " END"
)

# Reflect only plan_choices, not the tables its foreign keys name: SQLite
# can't reflect staff_users' expression index and warns on every run.
REFLECT = {"resolve_fks": False}

TRIGGERS = ("no_update", "no_delete", "no_overlap", "same_customer")

MONTHS_MATCH_PLAN = (
    "end_month IS CASE plan"
    " WHEN 'tri_monthly'"
    " THEN substr(date(start_month || '-01', '+2 months'), 1, 7)"
    " ELSE start_month END"
)
WHOLE_AGOROT = "typeof(unit_price_agorot) = 'integer' AND unit_price_agorot >= 0"


def _drop_triggers(names: Sequence[str]) -> None:
    for name in names:
        op.execute(f"DROP TRIGGER plan_choices_{name}")


def _create_append_only() -> None:
    for statement in APPEND_ONLY:
        op.execute(statement)


def upgrade() -> None:
    _drop_triggers(TRIGGERS)
    with op.batch_alter_table(
        "plan_choices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.alter_column(
            "plan", existing_type=sa.VARCHAR(length=20), nullable=True
        )
        batch_op.alter_column(
            "age_group", existing_type=sa.VARCHAR(length=20), nullable=True
        )
        batch_op.alter_column(
            "unit_price_agorot", existing_type=sa.INTEGER(), nullable=True
        )
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_months_match_plan"), type_="check"
        )
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_unit_price_is_whole_agorot"), type_="check"
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_months_match_plan"),
            f"plan IS NULL OR {MONTHS_MATCH_PLAN}",
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_unit_price_is_whole_agorot"),
            f"unit_price_agorot IS NULL OR ({WHOLE_AGOROT})",
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_no_plan_row_is_complete"),
            "(plan IS NULL) = (age_group IS NULL)"
            " AND (plan IS NULL) = (unit_price_agorot IS NULL)"
            " AND (plan IS NOT NULL OR replaces_id IS NOT NULL)",
        )
    _create_append_only()
    op.execute(NO_OVERLAP)
    op.execute(SAME_CUSTOMER)
    op.execute(SAME_MONTHS)


def downgrade() -> None:
    no_plan_rows = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM plan_choices WHERE plan IS NULL"))
        .scalar_one()
    )
    if no_plan_rows:
        raise RuntimeError(
            f'plan_choices has {no_plan_rows} "no plan" row(s), which the'
            " previous schema can't hold. Downgrading would delete history,"
            " so it stops here; nothing was changed."
        )
    _drop_triggers((*TRIGGERS, "same_months"))
    with op.batch_alter_table(
        "plan_choices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_no_plan_row_is_complete"), type_="check"
        )
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_unit_price_is_whole_agorot"), type_="check"
        )
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_months_match_plan"), type_="check"
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_months_match_plan"), MONTHS_MATCH_PLAN
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_unit_price_is_whole_agorot"), WHOLE_AGOROT
        )
        batch_op.alter_column(
            "unit_price_agorot", existing_type=sa.INTEGER(), nullable=False
        )
        batch_op.alter_column(
            "age_group", existing_type=sa.VARCHAR(length=20), nullable=False
        )
        batch_op.alter_column(
            "plan", existing_type=sa.VARCHAR(length=20), nullable=False
        )
    _create_append_only()
    op.execute(OLD_NO_OVERLAP)
    op.execute(SAME_CUSTOMER)
