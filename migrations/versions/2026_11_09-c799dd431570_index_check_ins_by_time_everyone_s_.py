"""index check-ins by time: everyone's visits in a stretch of time

Revision ID: c799dd431570
Revises: 23b9f8717ccd
Create Date: 2026-11-09 13:41:05.968227+00:00

A plain index on ``checkins.checked_in_at``, for reading every customer's
check-ins between two moments: today's on the dashboard, a month's for the
report. The existing ``(customer_id, checked_in_at)`` index only helps
when the customer is known.

No table rebuild and no data change: ``CREATE INDEX`` on the table as it
is. ``downgrade()`` drops the index: a full undo.
"""

from collections.abc import Sequence

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "c799dd431570"
down_revision: str | Sequence[str] | None = "23b9f8717ccd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_checkins_checked_in_at"), "checkins", ["checked_in_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_checkins_checked_in_at"), table_name="checkins")
