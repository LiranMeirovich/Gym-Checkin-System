"""add doctor notes table: a note that makes a "yes" health form count.

Revision ID: 006819ebd2e9
Revises: 57989f782d93
Create Date: 2026-11-05 10:08:19.763235+00:00

A new, empty table; no existing rows are touched and nothing is rebuilt.

Autogenerate can't see triggers, so two are written by hand: rows can't be
updated or deleted (a note is evidence for the insurer, and history is
never overwritten). SQLite drops a table's triggers with it, so a later
migration that rebuilds this table (batch mode) must create them again;
tests/test_models_doctor_notes.py checks they exist at head. The downgrade
drops the triggers and the table, which is a full undo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "006819ebd2e9"
down_revision: str | Sequence[str] | None = "57989f782d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doctor_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("health_form_id", sa.Integer(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False),
        sa.Column(
            "content_type",
            sa.Enum(
                "image/jpeg",
                "image/png",
                name="image_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("staff_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "typeof(image) = 'blob'"
            " AND length(image) <= 5242880"
            " AND ((content_type = 'image/jpeg'"
            " AND substr(image, 1, 3) IS X'FFD8FF')"
            " OR (content_type = 'image/png'"
            " AND substr(image, 1, 8) IS X'89504E470D0A1A0A'))",
            name=op.f("ck_doctor_notes_image_matches_its_type"),
        ),
        sa.ForeignKeyConstraint(
            ["health_form_id"],
            ["health_forms.id"],
            name=op.f("fk_doctor_notes_health_form_id_health_forms"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_doctor_notes_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_notes")),
    )
    with op.batch_alter_table("doctor_notes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_doctor_notes_health_form_id"),
            ["health_form_id"],
            unique=False,
        )
    op.execute(
        "CREATE TRIGGER doctor_notes_no_update BEFORE UPDATE ON doctor_notes"
        " BEGIN SELECT RAISE(ABORT, 'doctor_notes is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER doctor_notes_no_delete BEFORE DELETE ON doctor_notes"
        " BEGIN SELECT RAISE(ABORT, 'doctor_notes is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER doctor_notes_no_delete")
    op.execute("DROP TRIGGER doctor_notes_no_update")
    with op.batch_alter_table("doctor_notes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_doctor_notes_health_form_id"))

    op.drop_table("doctor_notes")
