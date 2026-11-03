"""Alembic migrations: they apply cleanly, undo cleanly, and match the
models."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from app.core.db import get_engine
from app.core.models import Base
from tests.conftest import AddMigration


def current_revision() -> str | None:
    with get_engine().connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_there_is_exactly_one_head(alembic_config: Config) -> None:
    # Two heads means two migrations claim the same parent (usually from
    # two branches); `upgrade head` would refuse to run.
    assert len(ScriptDirectory.from_config(alembic_config).get_heads()) == 1


def test_upgrade_reaches_head(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    head = ScriptDirectory.from_config(alembic_config).get_current_head()
    assert current_revision() == head


def test_every_migration_can_be_undone_and_reapplied(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    assert current_revision() is None

    command.upgrade(alembic_config, "head")
    head = ScriptDirectory.from_config(alembic_config).get_current_head()
    assert current_revision() == head


# SQLite can't reflect expression indexes, so this comparison can't see
# them (uq_staff_users_active_display_name); test_models_staff.py checks
# that one directly.
@pytest.mark.filterwarnings("ignore:.*expression-based index")
def test_migrations_match_the_models(alembic_config: Config) -> None:
    # Fails when a model changed without a migration (or the other way
    # round). Fix: `uv run alembic revision --autogenerate -m "..."`.
    command.upgrade(alembic_config, "head")

    with get_engine().connect() as connection:
        differences = compare_metadata(
            MigrationContext.configure(connection), Base.metadata
        )

    assert differences == []


# ── Foreign keys during migrations ──────────────────────────────────────
# These add a throwaway migration after the real head, from a temporary
# folder, to check how env.py runs migrations. Nothing is written to
# migrations/versions.

REBUILD_REFERENCED_TABLE = """
def upgrade() -> None:
    op.create_table(
        "parent", sa.Column("id", sa.Integer, primary_key=True)
    )
    op.create_table(
        "child",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "parent_id",
            sa.Integer,
            sa.ForeignKey("parent.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.execute("INSERT INTO parent (id) VALUES (1)")
    op.execute("INSERT INTO child (id, parent_id) VALUES (1, 1)")
    # Batch mode rebuilds "parent": copy, DROP the original, rename.
    with op.batch_alter_table("parent", recreate="always") as batch:
        batch.add_column(sa.Column("name", sa.Text))
"""

LEAVE_AN_ORPHAN = """
def upgrade() -> None:
    op.create_table(
        "parent", sa.Column("id", sa.Integer, primary_key=True)
    )
    op.create_table(
        "child",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("parent.id")),
    )
    op.execute("INSERT INTO child (id, parent_id) VALUES (1, 99)")
"""


def table_names() -> set[str]:
    with get_engine().connect() as connection:
        return set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).scalars()
        )


def test_rebuilding_a_referenced_table_keeps_the_rows_pointing_at_it(
    alembic_config: Config, add_test_migration: AddMigration
) -> None:
    # With foreign keys on, dropping "parent" during the rebuild would
    # cascade and delete the child row.
    revision = add_test_migration(REBUILD_REFERENCED_TABLE)

    command.upgrade(alembic_config, "head")

    assert current_revision() == revision
    with get_engine().connect() as connection:
        children = connection.exec_driver_sql("SELECT id, parent_id FROM child")
        assert children.fetchall() == [(1, 1)]


def test_a_migration_that_breaks_foreign_keys_is_rolled_back(
    alembic_config: Config, add_test_migration: AddMigration
) -> None:
    command.upgrade(alembic_config, "head")
    before = current_revision()
    add_test_migration(LEAVE_AN_ORPHAN)

    with pytest.raises(RuntimeError, match="child row 1 -> parent"):
        command.upgrade(alembic_config, "head")

    # Nothing from the failed upgrade remains, not even its tables.
    assert current_revision() == before
    assert {"parent", "child"}.isdisjoint(table_names())


def test_app_connections_still_enforce_foreign_keys_after_migrating(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")

    with get_engine().connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_offline_sql_scripts_are_refused(alembic_config: Config) -> None:
    # A printed SQL script would run without the foreign-key handling.
    with pytest.raises(RuntimeError, match="offline migrations"):
        command.upgrade(alembic_config, "head", sql=True)


# ── 818f444bb393: "no plan" rows in plan_choices ────────────────────────
# The table is rebuilt, so rows made before it must come through unchanged,
# and the downgrade must not drop history it can't hold.

BEFORE_NO_PLAN_ROWS = "391fa9399bd0"

SEED_PLAN_CHOICES = (
    "INSERT INTO customers (id, first_name, last_name, phone, date_of_birth,"
    " notes, created_at, active) VALUES (1, 'Dana', 'Levi', '+972501234567',"
    " '1990-05-01', '', '2026-10-30 09:00:00.000000', 1)",
    "INSERT INTO staff_users (id, display_name, role, pin_hash,"
    " failed_attempts, active, created_at) VALUES (1, 'Noa', 'manager',"
    " '$argon2id$v=19$m=65536,t=3,p=4$fake', 0, 1,"
    " '2026-10-30 09:00:00.000000')",
    "INSERT INTO plan_choices (id, customer_id, plan, start_month, end_month,"
    " age_group, unit_price_agorot, chosen_at, chosen_by, staff_user_id,"
    " replaces_id) VALUES"
    " (1, 1, 'single_entry', '2026-11', '2026-11', 'adult', 4000,"
    " '2026-11-03 09:00:00.000000', 'staff', 1, NULL),"
    " (2, 1, 'tri_monthly', '2026-11', '2027-01', 'adult', 60000,"
    " '2026-11-03 10:00:00.000000', 'customer', NULL, 1)",
)


def plan_choice_rows() -> list[tuple[object, ...]]:
    with get_engine().connect() as connection:
        return connection.exec_driver_sql(
            "SELECT * FROM plan_choices ORDER BY id"
        ).fetchall()


def test_plan_choices_come_through_the_no_plan_rebuild(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, BEFORE_NO_PLAN_ROWS)
    with get_engine().begin() as connection:
        for statement in SEED_PLAN_CHOICES:
            connection.exec_driver_sql(statement)
    before = plan_choice_rows()

    command.upgrade(alembic_config, "head")

    assert plan_choice_rows() == before
    # The rebuilt table is still append-only.
    with get_engine().begin() as connection, pytest.raises(IntegrityError):
        connection.exec_driver_sql("DELETE FROM plan_choices")


def test_the_downgrade_keeps_no_plan_rows(alembic_config: Config) -> None:
    command.upgrade(alembic_config, BEFORE_NO_PLAN_ROWS)
    with get_engine().begin() as connection:
        for statement in SEED_PLAN_CHOICES:
            connection.exec_driver_sql(statement)
    command.upgrade(alembic_config, "head")
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO plan_choices (customer_id, start_month, end_month,"
            " chosen_at, chosen_by, staff_user_id, replaces_id) VALUES"
            " (1, '2026-11', '2027-01', '2026-11-03 11:00:00.000000', 'staff',"
            " 1, 2)"
        )
    head = current_revision()

    with pytest.raises(RuntimeError, match="no plan"):
        command.downgrade(alembic_config, "-1")

    assert current_revision() == head
    assert len(plan_choice_rows()) == 3
