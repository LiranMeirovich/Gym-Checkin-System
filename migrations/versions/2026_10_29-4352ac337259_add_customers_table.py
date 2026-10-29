"""add customers table: gym members, one per normalised phone number.

Revision ID: 4352ac337259
Revises: 37b8063ce6e6
Create Date: 2026-10-29 13:51:08.404832+00:00

A new, empty table; no rows are added. The phone is unique across every
customer, active or not (decision 0023).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "4352ac337259"
down_revision: str | Sequence[str] | None = "37b8063ce6e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "active", sa.Boolean(create_constraint=True, name="active"), nullable=False
        ),
        sa.CheckConstraint(
            "phone GLOB '+972[1-9]*'"
            " AND substr(phone, 2) NOT GLOB '*[^0-9]*'"
            " AND length(phone) BETWEEN 12 AND 13",
            name=op.f("ck_customers_phone_is_e164_israeli"),
        ),
        sa.CheckConstraint(
            "date(date_of_birth) IS date_of_birth",
            name=op.f("ck_customers_date_of_birth_is_a_date"),
        ),
        sa.CheckConstraint(
            "length(first_name) BETWEEN 1 AND 50",
            name=op.f("ck_customers_first_name_length"),
        ),
        sa.CheckConstraint(
            "length(last_name) BETWEEN 1 AND 50",
            name=op.f("ck_customers_last_name_length"),
        ),
        sa.CheckConstraint(
            "length(notes) <= 256", name=op.f("ck_customers_notes_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("phone", name=op.f("uq_customers_phone")),
    )


def downgrade() -> None:
    op.drop_table("customers")
