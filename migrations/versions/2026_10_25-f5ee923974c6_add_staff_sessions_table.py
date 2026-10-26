"""add staff sessions table: one row per staff login, token stored hashed.

Revision ID: f5ee923974c6
Revises: 5eba85ff0b2a
Create Date: 2026-10-25 11:42:23.314791+00:00

A new, empty table; no existing rows are touched and nothing is rebuilt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "f5ee923974c6"
down_revision: str | Sequence[str] | None = "5eba85ff0b2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_staff_sessions_token_hash_is_sha256_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_staff_sessions_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_staff_sessions_token_hash")),
    )
    op.create_index(
        op.f("ix_staff_sessions_staff_user_id"),
        "staff_sessions",
        ["staff_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_staff_sessions_staff_user_id"), table_name="staff_sessions")
    op.drop_table("staff_sessions")
