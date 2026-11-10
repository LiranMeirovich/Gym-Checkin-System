"""add health form acceptances table: the manager accepting a "yes" form
without a doctor's note (decision 0041).

Revision ID: b0ca1ec058f5
Revises: c799dd431570
Create Date: 2026-11-10 08:22:21.886059+00:00

A new, empty table; no existing rows are touched and nothing is rebuilt.

Autogenerate can't see triggers, so two are written by hand: rows can't be
updated or deleted (who accepted a form stays on record). SQLite drops a
table's triggers with it, so a later migration that rebuilds this table
(batch mode) must create them again; tests/test_models_health_form_
acceptances.py checks they exist at head. The downgrade drops the triggers
and the table, which is a full undo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "b0ca1ec058f5"
down_revision: str | Sequence[str] | None = "c799dd431570"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "health_form_acceptances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("health_form_id", sa.Integer(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["health_form_id"],
            ["health_forms.id"],
            name=op.f("fk_health_form_acceptances_health_form_id_health_forms"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_health_form_acceptances_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_form_acceptances")),
        sa.UniqueConstraint(
            "health_form_id", name=op.f("uq_health_form_acceptances_health_form_id")
        ),
    )
    op.execute(
        "CREATE TRIGGER health_form_acceptances_no_update"
        " BEFORE UPDATE ON health_form_acceptances"
        " BEGIN SELECT RAISE(ABORT, 'health_form_acceptances is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER health_form_acceptances_no_delete"
        " BEFORE DELETE ON health_form_acceptances"
        " BEGIN SELECT RAISE(ABORT, 'health_form_acceptances is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER health_form_acceptances_no_delete")
    op.execute("DROP TRIGGER health_form_acceptances_no_update")
    op.drop_table("health_form_acceptances")
