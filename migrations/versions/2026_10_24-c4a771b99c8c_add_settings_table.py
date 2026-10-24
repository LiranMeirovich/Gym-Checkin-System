"""add settings table: values the manager edits in the admin app.

Revision ID: c4a771b99c8c
Revises: f581c708437c
Create Date: 2026-10-24 10:25:17.638837+00:00

One row per key, value stored as JSON text (decision 0014). No rows are
added: a key with no row uses its default from the code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "c4a771b99c8c"
down_revision: str | Sequence[str] | None = "f581c708437c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )


def downgrade() -> None:
    op.drop_table("settings")
