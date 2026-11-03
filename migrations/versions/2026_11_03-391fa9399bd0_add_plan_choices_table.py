"""add plan choices table: one row per plan chosen for a customer.

Revision ID: 391fa9399bd0
Revises: e0cb3a836415
Create Date: 2026-11-03 08:53:20.740555+00:00

A new, empty table; no existing rows are touched and nothing is rebuilt.

Autogenerate can't see triggers, so four are written by hand here: rows
can't be updated or deleted (a correction is a new row with
``replaces_id``), a new row can't give a customer-month a second active
choice, and a replacement must be an existing choice of the same customer
(which also stops a row replacing itself). SQLite drops a
table's triggers with it, so a later migration that rebuilds this table
(batch mode) must create them again; tests/test_models_plan_choices.py
checks they exist at head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "391fa9399bd0"
down_revision: str | Sequence[str] | None = "e0cb3a836415"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_choices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column(
            "plan",
            sa.Enum(
                "monthly",
                "tri_monthly",
                "single_entry",
                name="plan",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("start_month", sa.Text(), nullable=False),
        sa.Column("end_month", sa.Text(), nullable=False),
        sa.Column(
            "age_group",
            sa.Enum(
                "adult",
                "under_18",
                name="age_group",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("unit_price_agorot", sa.Integer(), nullable=False),
        sa.Column("chosen_at", sa.DateTime(), nullable=False),
        sa.Column(
            "chosen_by",
            sa.Enum(
                "customer",
                "staff",
                name="chosen_by",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("replaces_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(chosen_by = 'staff') = (staff_user_id IS NOT NULL)",
            name=op.f("ck_plan_choices_staff_choice_names_staff"),
        ),
        sa.CheckConstraint(
            "end_month IS CASE plan"
            " WHEN 'tri_monthly'"
            " THEN substr(date(start_month || '-01', '+2 months'), 1, 7)"
            " ELSE start_month END",
            name=op.f("ck_plan_choices_months_match_plan"),
        ),
        sa.CheckConstraint(
            "length(end_month) = 7"
            " AND end_month >= '1000-01'"
            " AND date(end_month || '-01') IS end_month || '-01'",
            name=op.f("ck_plan_choices_end_month_is_a_month"),
        ),
        sa.CheckConstraint(
            "length(start_month) = 7"
            " AND start_month >= '1000-01'"
            " AND date(start_month || '-01') IS start_month || '-01'",
            name=op.f("ck_plan_choices_start_month_is_a_month"),
        ),
        sa.CheckConstraint(
            "typeof(unit_price_agorot) = 'integer' AND unit_price_agorot >= 0",
            name=op.f("ck_plan_choices_unit_price_is_whole_agorot"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_plan_choices_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["replaces_id"],
            ["plan_choices.id"],
            name=op.f("fk_plan_choices_replaces_id_plan_choices"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_plan_choices_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_choices")),
        sa.UniqueConstraint("replaces_id", name=op.f("uq_plan_choices_replaces_id")),
    )
    with op.batch_alter_table("plan_choices", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_plan_choices_customer_id"),
            ["customer_id", "start_month"],
            unique=False,
        )
    op.execute(
        "CREATE TRIGGER plan_choices_no_update BEFORE UPDATE ON plan_choices"
        " BEGIN SELECT RAISE(ABORT, 'plan_choices is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER plan_choices_no_delete BEFORE DELETE ON plan_choices"
        " BEGIN SELECT RAISE(ABORT, 'plan_choices is append-only'); END"
    )
    # An active choice is one no row replaces. The row being replaced is
    # left out, so a correction is a single insert.
    op.execute(
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
    # Before the insert the new row doesn't exist yet, so this also refuses
    # a row that names itself.
    op.execute(
        "CREATE TRIGGER plan_choices_same_customer BEFORE INSERT ON plan_choices"
        " WHEN NEW.replaces_id IS NOT NULL"
        " AND (SELECT customer_id FROM plan_choices WHERE id = NEW.replaces_id)"
        " IS NOT NEW.customer_id"
        " BEGIN SELECT RAISE(ABORT,"
        " 'plan_choices: a choice replaces one of the same customer'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER plan_choices_same_customer")
    op.execute("DROP TRIGGER plan_choices_no_overlap")
    op.execute("DROP TRIGGER plan_choices_no_delete")
    op.execute("DROP TRIGGER plan_choices_no_update")
    with op.batch_alter_table("plan_choices", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plan_choices_customer_id"))

    op.drop_table("plan_choices")
