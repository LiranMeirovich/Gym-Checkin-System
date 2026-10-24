"""baseline: the empty starting point, before any tables.

Revision ID: f581c708437c
Revises:
Create Date: 2026-10-24 09:02:47.624780+00:00

Every later migration builds on this one, and the apps check that a
database is at the newest revision before they start.
"""

from collections.abc import Sequence

# Revision identifiers, used by Alembic.
revision: str = "f581c708437c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
