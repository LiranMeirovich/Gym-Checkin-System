"""add staff users table: managers and instructors, with hashed PINs.

Revision ID: 5eba85ff0b2a
Revises: c4a771b99c8c
Create Date: 2026-10-25 10:12:41.093905+00:00

A new, empty table; no rows are added (the first manager comes from
first-run setup). The partial unique index on active names is written by
hand: autogenerate skips expression indexes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "5eba85ff0b2a"
down_revision: str | Sequence[str] | None = "c4a771b99c8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "manager",
                "instructor",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column(
            "active", sa.Boolean(create_constraint=True, name="active"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "pin_hash LIKE '$argon2id$%'",
            name=op.f("ck_staff_users_pin_hash_is_argon2id"),
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name=op.f("ck_staff_users_failed_attempts_not_negative"),
        ),
        sa.CheckConstraint(
            "length(display_name) BETWEEN 1 AND 50",
            name=op.f("ck_staff_users_display_name_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_users")),
    )
    op.create_index(
        "uq_staff_users_active_display_name",
        "staff_users",
        [sa.text("lower(display_name)")],
        unique=True,
        sqlite_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("uq_staff_users_active_display_name", table_name="staff_users")
    op.drop_table("staff_users")
