"""add link codes and device sessions: linking a customer's phone.

Revision ID: 1f8cbff602b9
Revises: 818f444bb393
Create Date: 2026-11-03 16:06:03.279303+00:00

Two new, empty tables; no existing rows are touched and nothing is
rebuilt. The downgrade drops both, which is a full undo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "1f8cbff602b9"
down_revision: str | Sequence[str] | None = "818f444bb393"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_device_sessions_token_hash_is_sha256_hex"),
        ),
        sa.CheckConstraint(
            "length(user_agent) <= 200",
            name=op.f("ck_device_sessions_user_agent_length"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_device_sessions_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_device_sessions_token_hash")),
    )
    with op.batch_alter_table("device_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_device_sessions_customer_id"), ["customer_id"], unique=False
        )

    op.create_table(
        "link_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "length(code_hash) = 64 AND code_hash NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_link_codes_code_hash_is_sha256_hex"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_link_codes_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["staff_users.id"],
            name=op.f("fk_link_codes_created_by_staff_users"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_link_codes_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_link_codes")),
    )
    with op.batch_alter_table("link_codes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_link_codes_customer_id"), ["customer_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("link_codes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_link_codes_customer_id"))

    op.drop_table("link_codes")
    with op.batch_alter_table("device_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_device_sessions_customer_id"))

    op.drop_table("device_sessions")
