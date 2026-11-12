"""add report deliveries table: one row per step in delivering a report.

Revision ID: 763184ea3315
Revises: 5870901556ac
Create Date: 2026-11-12 13:46:38.426489+00:00

- ``report_deliveries``: a new, empty table. Each row is one step for one
  generation of a month's report: an email to the manager, the manager's
  approval, or an email to the recipients (sent or failed). Two triggers
  make it append-only.

No existing table changes. ``downgrade()`` is a full undo while the table is
empty, and refuses once any step is on record: unlike a report, who
approved it and what was sent can't be rebuilt from history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "763184ea3315"
down_revision: str | Sequence[str] | None = "5870901556ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = {
    "report_deliveries_no_update": (
        "CREATE TRIGGER report_deliveries_no_update"
        " BEFORE UPDATE ON report_deliveries"
        " BEGIN SELECT RAISE(ABORT, 'report_deliveries is append-only'); END"
    ),
    "report_deliveries_no_delete": (
        "CREATE TRIGGER report_deliveries_no_delete"
        " BEFORE DELETE ON report_deliveries"
        " BEGIN SELECT RAISE(ABORT, 'report_deliveries is append-only'); END"
    ),
}


def upgrade() -> None:
    op.create_table(
        "report_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "manager_email",
                "approval",
                "recipients_email",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "sent",
                "failed",
                name="outcome",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("recipients_json", sa.Text(), nullable=True),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(kind = 'approval') IS (outcome IS NULL)",
            name=op.f("ck_report_deliveries_email_has_an_outcome"),
        ),
        sa.CheckConstraint(
            "(kind = 'approval') IS (recipients_json IS NULL)",
            name=op.f("ck_report_deliveries_email_has_recipients"),
        ),
        sa.CheckConstraint(
            "kind != 'approval' OR staff_user_id IS NOT NULL",
            name=op.f("ck_report_deliveries_approval_names_staff"),
        ),
        sa.CheckConstraint(
            "recipients_json IS NULL"
            " OR (json_valid(recipients_json)"
            " AND json_type(recipients_json) = 'array')",
            name=op.f("ck_report_deliveries_recipients_are_a_json_list"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_report_deliveries_report_id_reports"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_report_deliveries_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_deliveries")),
    )
    op.create_index(
        op.f("ix_report_deliveries_report_id"),
        "report_deliveries",
        ["report_id", "id"],
        unique=False,
    )
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    steps = (
        op.get_bind().exec_driver_sql("SELECT count(*) FROM report_deliveries").scalar()
    )
    if steps:
        raise RuntimeError(
            f"can't undo report deliveries: {steps} delivery step(s) exist"
            " (emails, approvals), and undoing would delete them"
        )
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    op.drop_index(
        op.f("ix_report_deliveries_report_id"), table_name="report_deliveries"
    )
    op.drop_table("report_deliveries")
