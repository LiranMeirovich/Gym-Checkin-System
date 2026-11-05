"""add checkins table: one row per visit, append-only.

Revision ID: 57989f782d93
Revises: 85868e91c939
Create Date: 2026-11-05 08:08:02.441285+00:00

A new, empty table; no existing rows are touched and nothing is rebuilt.

Autogenerate can't see triggers, so three are written by hand: rows can't
be updated or deleted (single-entry billing counts them, and past reports
must regenerate identically), and a phone check-in's device session must
belong to the same customer. SQLite drops a table's triggers with it, so a
later migration that rebuilds this table (batch mode) must create them
again; tests/test_models_checkins.py checks they exist at head. The
downgrade drops the triggers and the table, which is a full undo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "57989f782d93"
down_revision: str | Sequence[str] | None = "85868e91c939"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checkins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "phone",
                "manual",
                name="checkin_method",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("device_session_id", sa.Integer(), nullable=True),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(method = 'phone') = (device_session_id IS NOT NULL)"
            " AND (method = 'manual') = (staff_user_id IS NOT NULL)",
            name=op.f("ck_checkins_method_names_its_source"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_checkins_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["device_session_id"],
            ["device_sessions.id"],
            name=op.f("fk_checkins_device_session_id_device_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_checkins_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkins")),
    )
    with op.batch_alter_table("checkins", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_checkins_customer_id"),
            ["customer_id", "checked_in_at"],
            unique=False,
        )
    op.execute(
        "CREATE TRIGGER checkins_no_update BEFORE UPDATE ON checkins"
        " BEGIN SELECT RAISE(ABORT, 'checkins is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER checkins_no_delete BEFORE DELETE ON checkins"
        " BEGIN SELECT RAISE(ABORT, 'checkins is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER checkins_same_customer_device BEFORE INSERT ON checkins"
        " WHEN NEW.device_session_id IS NOT NULL"
        " AND (SELECT customer_id FROM device_sessions"
        " WHERE id = NEW.device_session_id) IS NOT NEW.customer_id"
        " BEGIN SELECT RAISE(ABORT,"
        " 'checkins: a phone check-in uses the same customer''s phone'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER checkins_same_customer_device")
    op.execute("DROP TRIGGER checkins_no_delete")
    op.execute("DROP TRIGGER checkins_no_update")
    with op.batch_alter_table("checkins", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_checkins_customer_id"))

    op.drop_table("checkins")
