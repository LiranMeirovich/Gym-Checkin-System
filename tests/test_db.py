"""Database engine and request sessions: pragmas, and one transaction per
request."""

from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import BUSY_TIMEOUT_MS, create_db_engine, get_db, get_engine


def test_pragmas_are_set_on_every_connection(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "test.db")

    with engine.connect() as connection:

        def pragma(name: str) -> object:
            return connection.exec_driver_sql(f"PRAGMA {name}").scalar()

        assert pragma("journal_mode") == "wal"
        assert pragma("foreign_keys") == 1
        assert pragma("busy_timeout") == BUSY_TIMEOUT_MS
        assert pragma("synchronous") == 1  # NORMAL

    engine.dispose()


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "test.db")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE child (id INTEGER PRIMARY KEY,"
            " parent_id INTEGER NOT NULL REFERENCES parent (id))"
        )

    with (
        pytest.raises(IntegrityError, match="FOREIGN KEY"),
        engine.begin() as connection,
    ):
        connection.exec_driver_sql("INSERT INTO child (parent_id) VALUES (99)")

    engine.dispose()


def test_get_engine_uses_the_configured_path(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_DATABASE_PATH", "configured.db")

    with get_engine().connect():
        pass

    assert (isolated_env / "configured.db").exists()
    assert get_engine() is get_engine()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A throwaway app with one route that writes a row, then succeeds or
    fails depending on the request."""
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    with get_engine().begin() as connection:
        connection.exec_driver_sql("CREATE TABLE note (body TEXT NOT NULL)")

    app = FastAPI()

    @app.post("/notes/{body}")
    def add_note(
        body: str, db: Annotated[Session, Depends(get_db)], fail: str = ""
    ) -> None:
        db.execute(text("INSERT INTO note (body) VALUES (:body)"), {"body": body})
        if fail == "http":
            raise HTTPException(status_code=400)
        if fail == "crash":
            raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def saved_notes() -> list[str]:
    with get_engine().connect() as connection:
        return list(connection.exec_driver_sql("SELECT body FROM note").scalars())


def test_request_changes_are_committed(client: TestClient) -> None:
    assert client.post("/notes/kept").status_code == 200

    assert saved_notes() == ["kept"]


@pytest.mark.parametrize(("fail", "status"), [("http", 400), ("crash", 500)])
def test_request_changes_are_rolled_back_on_error(
    client: TestClient, fail: str, status: int
) -> None:
    assert client.post(f"/notes/lost?fail={fail}").status_code == status

    assert saved_notes() == []
