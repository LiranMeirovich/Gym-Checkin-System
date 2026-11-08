"""drop age group from prices and plan choices: one price per plan.

Revision ID: c3e4bdafa3d3
Revises: 006819ebd2e9
Create Date: 2026-11-08 10:08:38.026729+00:00

The manager dropped the under-18 prices (decision 0036), so ``age_group``
leaves both tables:

- ``prices``: the ``under_18`` rows are deleted and the adult rows stay as
  each plan's price. The column, its CHECK and its place in the
  ``(plan, age_group, valid_from_month)`` index go. Deleting rows is
  acceptable only because the system isn't live yet: no real price was
  ever charged from them.
- ``plan_choices``: the column and its CHECK go, and
  ``no_plan_row_is_complete`` keeps only the plan/price pairing. Every row
  stays, with the price that was copied onto it.

Both tables are rebuilt (batch mode). SQLite drops a table's triggers with
it, so ``plan_choices``' five triggers are dropped first and created again
afterwards, unchanged (``prices`` has none).

``downgrade()`` restores the schema but not the deleted rows: every price
row and every real choice gets ``adult``, and "no plan" rows stay without
an age group. The under-18 prices are gone for good.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "c3e4bdafa3d3"
down_revision: str | Sequence[str] | None = "006819ebd2e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reflect only the rebuilt table, not the tables its foreign keys name:
# SQLite can't reflect staff_users' expression index and warns on every run.
REFLECT = {"resolve_fks": False}

# plan_choices' triggers as they stand at 818f444bb393, unchanged.
TRIGGERS = {
    "no_update": (
        "CREATE TRIGGER plan_choices_no_update BEFORE UPDATE ON plan_choices"
        " BEGIN SELECT RAISE(ABORT, 'plan_choices is append-only'); END"
    ),
    "no_delete": (
        "CREATE TRIGGER plan_choices_no_delete BEFORE DELETE ON plan_choices"
        " BEGIN SELECT RAISE(ABORT, 'plan_choices is append-only'); END"
    ),
    "no_overlap": (
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
    ),
    "same_customer": (
        "CREATE TRIGGER plan_choices_same_customer BEFORE INSERT ON plan_choices"
        " WHEN NEW.replaces_id IS NOT NULL"
        " AND (SELECT customer_id FROM plan_choices WHERE id = NEW.replaces_id)"
        " IS NOT NEW.customer_id"
        " BEGIN SELECT RAISE(ABORT,"
        " 'plan_choices: a choice replaces one of the same customer'); END"
    ),
    "same_months": (
        "CREATE TRIGGER plan_choices_same_months BEFORE INSERT ON plan_choices"
        " WHEN NEW.replaces_id IS NOT NULL AND ("
        "(SELECT start_month FROM plan_choices WHERE id = NEW.replaces_id)"
        " != NEW.start_month"
        " OR (NEW.plan IS NULL"
        " AND (SELECT end_month FROM plan_choices WHERE id = NEW.replaces_id)"
        " != NEW.end_month))"
        " BEGIN SELECT RAISE(ABORT,"
        " 'plan_choices: a correction keeps the months of the choice it"
        " replaces'); END"
    ),
}

AGE_GROUPS = "age_group IN ('adult', 'under_18')"
NO_PLAN_ROW_IS_COMPLETE = (
    "(plan IS NULL) = (unit_price_agorot IS NULL)"
    " AND (plan IS NOT NULL OR replaces_id IS NOT NULL)"
)
OLD_NO_PLAN_ROW_IS_COMPLETE = (
    f"(plan IS NULL) = (age_group IS NULL) AND {NO_PLAN_ROW_IS_COMPLETE}"
)


def _drop_triggers() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER plan_choices_{name}")


def _create_triggers() -> None:
    for statement in TRIGGERS.values():
        op.execute(statement)


def upgrade() -> None:
    op.execute("DELETE FROM prices WHERE age_group = 'under_18'")
    with op.batch_alter_table(
        "prices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prices_plan"))
        batch_op.drop_constraint(batch_op.f("ck_prices_age_group"), type_="check")
        batch_op.drop_column("age_group")
        batch_op.create_index(
            batch_op.f("ix_prices_plan"), ["plan", "valid_from_month"], unique=False
        )

    _drop_triggers()
    with op.batch_alter_table(
        "plan_choices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_no_plan_row_is_complete"), type_="check"
        )
        batch_op.drop_constraint(batch_op.f("ck_plan_choices_age_group"), type_="check")
        batch_op.drop_column("age_group")
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_no_plan_row_is_complete"),
            NO_PLAN_ROW_IS_COMPLETE,
        )
    _create_triggers()


def downgrade() -> None:
    # Every remaining price was an adult one.
    with op.batch_alter_table(
        "prices", schema=None, reflect_kwargs=REFLECT, recreate="always"
    ) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prices_plan"))
        batch_op.add_column(
            sa.Column(
                "age_group",
                sa.VARCHAR(length=20),
                nullable=False,
                server_default="adult",
            ),
            insert_before="amount_agorot",
        )
    with op.batch_alter_table(
        "prices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.alter_column(
            "age_group", existing_type=sa.VARCHAR(length=20), server_default=None
        )
        batch_op.create_check_constraint(batch_op.f("ck_prices_age_group"), AGE_GROUPS)
        batch_op.create_index(
            batch_op.f("ix_prices_plan"),
            ["plan", "age_group", "valid_from_month"],
            unique=False,
        )

    # The triggers refuse the UPDATE that fills the column, so they stay off
    # until both rebuilds are done.
    _drop_triggers()
    with op.batch_alter_table(
        "plan_choices", schema=None, reflect_kwargs=REFLECT, recreate="always"
    ) as batch_op:
        batch_op.add_column(
            sa.Column("age_group", sa.VARCHAR(length=20), nullable=True),
            insert_after="end_month",
        )
    op.execute("UPDATE plan_choices SET age_group = 'adult' WHERE plan IS NOT NULL")
    with op.batch_alter_table(
        "plan_choices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_plan_choices_no_plan_row_is_complete"), type_="check"
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_age_group"), AGE_GROUPS
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_plan_choices_no_plan_row_is_complete"),
            OLD_NO_PLAN_ROW_IS_COMPLETE,
        )
    _create_triggers()
