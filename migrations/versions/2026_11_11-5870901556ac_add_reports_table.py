"""add reports table: one row per generation of a month's report.

Revision ID: 5870901556ac
Revises: 8e3f21ab05b0
Create Date: 2026-11-11 12:50:30.638375+00:00

- ``reports``: a new, empty table. Two triggers make it append-only:
  regenerating adds a row, and the newest row for a month is its report.

No existing table changes. ``downgrade()`` is a full undo and drops the
table even with rows in it: every report regenerates identically from
history, and the activity log keeps who generated what.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "5870901556ac"
down_revision: str | Sequence[str] | None = "8e3f21ab05b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORTS_TRIGGERS = {
    "reports_no_update": (
        "CREATE TRIGGER reports_no_update BEFORE UPDATE ON reports"
        " BEGIN SELECT RAISE(ABORT, 'reports is append-only'); END"
    ),
    "reports_no_delete": (
        "CREATE TRIGGER reports_no_delete BEFORE DELETE ON reports"
        " BEGIN SELECT RAISE(ABORT, 'reports is append-only'); END"
    ),
}


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("rows_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(month) = 7"
            " AND month >= '1000-01'"
            " AND date(month || '-01') IS month || '-01'",
            name=op.f("ck_reports_month_is_a_month"),
        ),
        sa.CheckConstraint(
            "json_valid(rows_json)", name=op.f("ck_reports_rows_are_json")
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_reports_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_month"), "reports", ["month", "id"], unique=False)
    for statement in REPORTS_TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in REPORTS_TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    op.drop_index(op.f("ix_reports_month"), table_name="reports")
    op.drop_table("reports")
