"""Shared test setup."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.startup import ALEMBIC_INI


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run each test in an empty directory with no GYM_* variables, so the
    developer's own .env or environment never leaks into a test. The cached
    settings and engine are reset around each test, so each test's database
    is a file in its own directory."""
    for name in list(os.environ):
        if name.startswith("GYM_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield tmp_path
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic's config, in dev mode. isolated_env runs each test in its own
    directory, so the default database path (gym.db) is a fresh file there."""
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    return Config(ALEMBIC_INI)


@pytest.fixture
def migrated_db(alembic_config: Config) -> Path:
    """A database upgraded to the newest migration, as the apps require.
    Returns its path."""
    command.upgrade(alembic_config, "head")
    return get_settings().database_path


# Takes the source of an ``upgrade()`` function, returns the revision id.
type AddMigration = Callable[[str], str]


@pytest.fixture
def add_test_migration(alembic_config: Config, tmp_path: Path) -> AddMigration:
    """Add a throwaway migration after the newest real one, from a temporary
    folder that ``alembic_config`` also reads. Nothing is written to
    migrations/versions."""
    folder = tmp_path / "test_versions"
    folder.mkdir()
    real_versions = ALEMBIC_INI.parent / "migrations" / "versions"
    alembic_config.set_main_option(
        "version_locations", os.pathsep.join([str(real_versions), str(folder)])
    )

    def add(upgrade_source: str) -> str:
        head = ScriptDirectory.from_config(alembic_config).get_current_head()
        (folder / "test_migration.py").write_text(
            "import sqlalchemy as sa\n"
            "from alembic import op\n\n"
            "revision = 'test_migration'\n"
            f"down_revision = {head!r}\n"
            "branch_labels = None\n"
            "depends_on = None\n"
            f"{upgrade_source}\n\n"
            "def downgrade() -> None:\n"
            "    pass\n",
            encoding="utf-8",
        )
        return "test_migration"

    return add
