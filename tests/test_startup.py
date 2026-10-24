"""Shared startup: both apps refuse to start unless the database exists and
is at the newest migration."""

from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.main import app as admin_app
from app.core.db import get_engine
from app.core.startup import DatabaseNotReadyError, check_database_is_current
from app.public.main import app as public_app
from tests.conftest import AddMigration

both_apps = pytest.mark.parametrize(
    "app", [admin_app, public_app], ids=["admin", "public"]
)


def start(app: FastAPI) -> None:
    """Run the app's startup and shutdown."""
    with TestClient(app):
        pass


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_starts_on_a_migrated_database(app: FastAPI) -> None:
    start(app)


@both_apps
@pytest.mark.usefixtures("alembic_config")
def test_refuses_a_missing_database_without_creating_one(
    app: FastAPI, isolated_env: Path
) -> None:
    # Like starting the app from the wrong folder.
    with pytest.raises(DatabaseNotReadyError, match="no database at"):
        start(app)

    assert not (isolated_env / "gym.db").exists()


@both_apps
@pytest.mark.usefixtures("alembic_config")
def test_refuses_a_database_that_was_never_migrated(app: FastAPI) -> None:
    with get_engine().connect():  # creates an empty file
        pass

    with pytest.raises(DatabaseNotReadyError, match="never migrated"):
        start(app)


@pytest.mark.usefixtures("migrated_db")
def test_refuses_a_database_behind_the_newest_migration(
    alembic_config: Config, add_test_migration: AddMigration
) -> None:
    # A migration the database hasn't run yet, as after pulling new code.
    add_test_migration("def upgrade() -> None:\n    pass\n")

    with pytest.raises(DatabaseNotReadyError, match="but the newest is test_migration"):
        check_database_is_current(alembic_config)


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_refuses_a_database_upgraded_by_newer_code(app: FastAPI) -> None:
    # Like going back to an older version after a newer one migrated.
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            "UPDATE alembic_version SET version_num = 'from_the_future'"
        )

    with pytest.raises(DatabaseNotReadyError, match="doesn't know"):
        start(app)


@pytest.mark.usefixtures("migrated_db")
def test_shutdown_closes_database_connections() -> None:
    start(admin_app)

    assert get_engine().pool.checkedout() == 0
    assert get_engine().pool.checkedin() == 0
