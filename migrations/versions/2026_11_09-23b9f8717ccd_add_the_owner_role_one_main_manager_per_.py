"""add the owner role: one main manager per gym.

Revision ID: 23b9f8717ccd
Revises: c3e4bdafa3d3
Create Date: 2026-11-09 08:29:32.109515+00:00

``staff_users.role`` also allows ``owner``: the gym's main manager, who
alone manages the other managers and whose account nobody else can change.
A partial unique index lets at most one row be the owner.

Existing databases get an owner straight away: the oldest active manager
(lowest id). Without one, nobody could manage managers.

The table is rebuilt (batch mode) to change the role CHECK; rows are copied
unchanged. SQLite can't reflect the expression index on the name, so it's
dropped first and created again afterwards.

``downgrade()`` turns the owner back into a manager and restores the old
CHECK: a full undo of the schema; only which manager was the owner is lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "23b9f8717ccd"
down_revision: str | Sequence[str] | None = "c3e4bdafa3d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK = "ck_staff_users_role"
NAME_INDEX = "uq_staff_users_active_display_name"
OWNER_INDEX = "uq_staff_users_one_owner"


def _drop_name_index() -> None:
    op.drop_index(NAME_INDEX, table_name="staff_users")


def _create_name_index() -> None:
    op.create_index(
        NAME_INDEX,
        "staff_users",
        [sa.text("lower(display_name)")],
        unique=True,
        sqlite_where=sa.text("active"),
    )


def _replace_role_check(roles: Sequence[str]) -> None:
    allowed = ", ".join(f"'{role}'" for role in roles)
    with op.batch_alter_table("staff_users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(ROLE_CHECK), type_="check")
        batch_op.create_check_constraint(batch_op.f(ROLE_CHECK), f"role IN ({allowed})")


def upgrade() -> None:
    _drop_name_index()
    _replace_role_check(("owner", "manager", "instructor"))
    _create_name_index()
    op.create_index(
        OWNER_INDEX,
        "staff_users",
        ["role"],
        unique=True,
        sqlite_where=sa.text("role = 'owner'"),
    )
    op.execute(
        "UPDATE staff_users SET role = 'owner' WHERE id = ("
        "SELECT min(id) FROM staff_users WHERE role = 'manager' AND active)"
    )


def downgrade() -> None:
    op.execute("UPDATE staff_users SET role = 'manager' WHERE role = 'owner'")
    op.drop_index(OWNER_INDEX, table_name="staff_users")
    _drop_name_index()
    _replace_role_check(("manager", "instructor"))
    _create_name_index()
