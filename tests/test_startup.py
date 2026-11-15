"""Shared startup: both apps refuse to start unless the database exists,
opens with the configured key and is at the newest migration."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.main import app as admin_app
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.startup import (
    SQLITE_HEADER,
    DatabaseNotReadyError,
    check_database_is_current,
)
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


# ── The database key ────────────────────────────────────────────────────

# Made up; real keys never appear in the repo.
KEY = "ab" * 32
OTHER_KEY = "cd" * 32


def use_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    """Switch GYM_DATABASE_KEY, as if the app were restarted with it."""
    if key is None:
        monkeypatch.delenv("GYM_DATABASE_KEY", raising=False)
    else:
        monkeypatch.setenv("GYM_DATABASE_KEY", key)
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def encrypted_db(alembic_config: Config, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A migrated database encrypted with KEY."""
    use_key(monkeypatch, KEY)
    command.upgrade(alembic_config, "head")
    return get_settings().database_path


@pytest.fixture
def plain_db(alembic_config: Config, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A migrated database that isn't encrypted (dev without a key)."""
    use_key(monkeypatch, None)
    command.upgrade(alembic_config, "head")
    return get_settings().database_path


@both_apps
@pytest.mark.usefixtures("encrypted_db")
def test_starts_on_an_encrypted_database_with_its_key(app: FastAPI) -> None:
    start(app)


@both_apps
@pytest.mark.usefixtures("plain_db")
def test_starts_on_a_plain_database_without_a_key(app: FastAPI) -> None:
    start(app)


@both_apps
@pytest.mark.usefixtures("plain_db")
def test_refuses_a_plain_database_when_a_key_is_set(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_key(monkeypatch, KEY)

    with pytest.raises(
        DatabaseNotReadyError, match="is not encrypted.*encrypt_database"
    ):
        start(app)


@both_apps
@pytest.mark.usefixtures("encrypted_db")
def test_refuses_an_encrypted_database_without_a_key(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_key(monkeypatch, None)

    with pytest.raises(DatabaseNotReadyError, match="GYM_DATABASE_KEY isn't set"):
        start(app)


@both_apps
@pytest.mark.usefixtures("encrypted_db")
def test_refuses_an_encrypted_database_with_the_wrong_key(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_key(monkeypatch, OTHER_KEY)

    with pytest.raises(DatabaseNotReadyError, match="key is wrong"):
        start(app)


@pytest.mark.parametrize(
    ("key", "message"),
    [(None, "isn't set"), (OTHER_KEY, "key is wrong")],
)
def test_alembic_refuses_a_key_that_cant_open_the_database(
    encrypted_db: Path,
    alembic_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    key: str | None,
    message: str,
) -> None:
    before = encrypted_db.read_bytes()
    use_key(monkeypatch, key)

    with pytest.raises(DatabaseNotReadyError, match=message):
        command.upgrade(alembic_config, "head")

    assert encrypted_db.read_bytes() == before


@pytest.mark.usefixtures("plain_db")
def test_alembic_refuses_to_upgrade_a_plain_database_with_a_key(
    alembic_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_key(monkeypatch, KEY)

    with pytest.raises(DatabaseNotReadyError, match="is not encrypted"):
        command.upgrade(alembic_config, "head")


def test_alembic_creates_a_new_database_encrypted(
    encrypted_db: Path,
) -> None:
    assert not encrypted_db.read_bytes().startswith(SQLITE_HEADER)


@pytest.mark.usefixtures("migrated_db")
def test_shutdown_closes_database_connections() -> None:
    start(admin_app)

    assert get_engine().pool.checkedout() == 0
    assert get_engine().pool.checkedin() == 0
