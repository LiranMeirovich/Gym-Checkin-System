"""Alembic migrations: they apply cleanly, undo cleanly, and match the
models."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.db import get_engine
from app.core.models import Base

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    # isolated_env runs each test in its own directory, so the default
    # database path (gym.db) is a fresh file there.
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    return Config(ALEMBIC_INI)


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


def add_test_migration(config: Config, folder: Path, body: str) -> str:
    """Write a migration with ``body`` after the current head and make
    Alembic look in ``folder`` too. Returns its revision id."""
    head = ScriptDirectory.from_config(config).get_current_head()
    (folder / "test_migration.py").write_text(
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        "revision = 'test_migration'\n"
        f"down_revision = {head!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        f"{body}\n\n"
        "def downgrade() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    real_versions = ALEMBIC_INI.parent / "migrations" / "versions"
    config.set_main_option(
        "version_locations", os.pathsep.join([str(real_versions), str(folder)])
    )
    return "test_migration"


def table_names() -> set[str]:
    with get_engine().connect() as connection:
        return set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).scalars()
        )


def test_rebuilding_a_referenced_table_keeps_the_rows_pointing_at_it(
    alembic_config: Config, tmp_path: Path
) -> None:
    # With foreign keys on, dropping "parent" during the rebuild would
    # cascade and delete the child row.
    folder = tmp_path / "test_versions"
    folder.mkdir()
    revision = add_test_migration(alembic_config, folder, REBUILD_REFERENCED_TABLE)

    command.upgrade(alembic_config, "head")

    assert current_revision() == revision
    with get_engine().connect() as connection:
        children = connection.exec_driver_sql("SELECT id, parent_id FROM child")
        assert children.fetchall() == [(1, 1)]


def test_a_migration_that_breaks_foreign_keys_is_rolled_back(
    alembic_config: Config, tmp_path: Path
) -> None:
    command.upgrade(alembic_config, "head")
    before = current_revision()
    folder = tmp_path / "test_versions"
    folder.mkdir()
    add_test_migration(alembic_config, folder, LEAVE_AN_ORPHAN)

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
