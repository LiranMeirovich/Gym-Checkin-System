"""add prices table: the manager's price table, one row per price change.

Revision ID: e0cb3a836415
Revises: 4352ac337259
Create Date: 2026-10-30 10:25:52.703479+00:00

A new, empty table; no rows are added, so no prices exist until the manager
enters them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "e0cb3a836415"
down_revision: str | Sequence[str] | None = "4352ac337259"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), nullable=False),
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
        sa.Column("amount_agorot", sa.Integer(), nullable=False),
        sa.Column("valid_from_month", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(valid_from_month) = 7"
            " AND valid_from_month >= '1000-01'"
            " AND date(valid_from_month || '-01') IS valid_from_month || '-01'",
            name=op.f("ck_prices_valid_from_month_is_a_month"),
        ),
        sa.CheckConstraint(
            "typeof(amount_agorot) = 'integer' AND amount_agorot >= 0",
            name=op.f("ck_prices_amount_is_whole_agorot"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prices")),
    )
    with op.batch_alter_table("prices", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_prices_plan"),
            ["plan", "age_group", "valid_from_month"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("prices", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prices_plan"))

    op.drop_table("prices")
