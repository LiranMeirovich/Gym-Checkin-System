"""add activity log table: one row per staff change, append-only.

Revision ID: 37b8063ce6e6
Revises: f5ee923974c6
Create Date: 2026-10-26 13:57:12.290678+00:00

A new, empty table; no existing rows are touched and nothing is rebuilt.

Two triggers refuse UPDATE and DELETE on it. Autogenerate can't see
triggers, so they're written by hand here. SQLite drops a table's triggers
with it, so a later migration that rebuilds this table (batch mode) must
create them again; tests/test_models_activity_log.py checks they exist at
head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "37b8063ce6e6"
down_revision: str | Sequence[str] | None = "f5ee923974c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "after_json IS NULL OR json_valid(after_json)",
            name=op.f("ck_activity_log_after_json_is_json"),
        ),
        sa.CheckConstraint(
            "before_json IS NULL OR json_valid(before_json)",
            name=op.f("ck_activity_log_before_json_is_json"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_activity_log_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_log")),
    )
    op.create_index(op.f("ix_activity_log_at"), "activity_log", ["at"], unique=False)
    op.create_index(
        op.f("ix_activity_log_staff_user_id"),
        "activity_log",
        ["staff_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_log_target",
        "activity_log",
        ["target_type", "target_id"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER activity_log_no_update BEFORE UPDATE ON activity_log"
        " BEGIN SELECT RAISE(ABORT, 'activity_log is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER activity_log_no_delete BEFORE DELETE ON activity_log"
        " BEGIN SELECT RAISE(ABORT, 'activity_log is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER activity_log_no_delete")
    op.execute("DROP TRIGGER activity_log_no_update")
    op.drop_index("ix_activity_log_target", table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_staff_user_id"), table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_at"), table_name="activity_log")
    op.drop_table("activity_log")
