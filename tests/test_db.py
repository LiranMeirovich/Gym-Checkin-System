"""Database engine and request sessions: pragmas, one transaction per
request, and requests starting with BEGIN IMMEDIATE."""

import contextlib
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.types import Receive, Scope, Send

from app.core.db import (
    BUSY_TIMEOUT_MS,
    DbSession,
    create_db_engine,
    get_db,
    get_engine,
    get_read_only_db,
)


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


@pytest.mark.parametrize("name", ["gym?mode=ro.db", "gym #1 100%.db"])
def test_special_characters_in_the_path_are_part_of_the_file_name(
    tmp_path: Path, name: str
) -> None:
    # In a URL "?" starts a query string; it must stay part of the file name
    # (Windows forbids it in file names, Linux doesn't). Nothing is opened
    # here, so the test runs on both.
    path = tmp_path / name
    engine = create_db_engine(path)

    assert engine.url.database == str(path)
    assert not engine.url.query


def saved_notes() -> list[str]:
    """The notes committed so far, read on a connection of its own."""
    with get_engine().connect() as connection:
        return list(connection.exec_driver_sql("SELECT body FROM note").scalars())


class RecordingResponse(Response):
    """Records which notes were committed at the moment the response starts
    going out to the client."""

    seen_while_sending: list[list[str]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.seen_while_sending.append(saved_notes())
        await super().__call__(scope, receive, send)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A throwaway app with one route that writes a row, then succeeds or
    fails depending on the request."""
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    with get_engine().begin() as connection:
        connection.exec_driver_sql("CREATE TABLE note (body TEXT NOT NULL)")

    app = FastAPI()

    @app.post("/notes/{body}", response_class=RecordingResponse)
    def add_note(body: str, db: DbSession, fail: str = "") -> RecordingResponse:
        db.execute(text("INSERT INTO note (body) VALUES (:body)"), {"body": body})
        if fail == "http":
            raise HTTPException(status_code=400)
        if fail == "crash":
            raise RuntimeError("boom")
        return RecordingResponse()

    RecordingResponse.seen_while_sending = []
    yield TestClient(app, raise_server_exceptions=False)


def test_request_changes_are_committed_before_the_response_is_sent(
    client: TestClient,
) -> None:
    assert client.post("/notes/kept").status_code == 200

    # Already saved when the response went out, not some time after.
    assert RecordingResponse.seen_while_sending == [["kept"]]
    assert saved_notes() == ["kept"]


@pytest.mark.parametrize(("fail", "status"), [("http", 400), ("crash", 500)])
def test_request_changes_are_rolled_back_on_error(
    client: TestClient, fail: str, status: int
) -> None:
    assert client.post(f"/notes/lost?fail={fail}").status_code == status

    assert saved_notes() == []


# ── BEGIN IMMEDIATE for requests ────────────────────────────────────────


@pytest.fixture
def notes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    with get_engine().begin() as connection:
        connection.exec_driver_sql("CREATE TABLE note (body TEXT NOT NULL)")


def other_writer() -> sqlite3.Connection:
    """A connection of its own that gives up at once if it can't write."""
    connection = sqlite3.connect(get_engine().url.database, timeout=0)
    connection.isolation_level = None
    return connection


def test_a_request_holds_the_write_lock_from_its_first_read(notes: None) -> None:
    session = get_db()
    db = next(session)
    db.execute(text("SELECT count(*) FROM note"))

    writer = other_writer()
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute("BEGIN IMMEDIATE")
    finally:
        writer.close()
        session.close()


def test_other_transactions_keep_a_plain_begin(notes: None) -> None:
    with get_engine().begin() as connection:
        connection.exec_driver_sql("SELECT count(*) FROM note")
        writer = other_writer()
        try:
            # A read takes no write lock, so another writer gets in.
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("ROLLBACK")
        finally:
            writer.close()


def test_a_second_request_waits_and_sees_what_the_first_saved(notes: None) -> None:
    # Without IMMEDIATE the second would read 0 at once, and its write
    # after the first commit would fail with "database is locked".
    seen: list[int] = []
    first = get_db()
    db = next(first)
    db.execute(text("INSERT INTO note (body) VALUES ('first')"))

    def second_request() -> None:
        session = get_db()
        second = next(session)
        seen.append(second.scalar(text("SELECT count(*) FROM note")))
        second.execute(text("INSERT INTO note (body) VALUES ('second')"))
        with contextlib.suppress(StopIteration):
            next(session)

    waiting = threading.Thread(target=second_request)
    waiting.start()
    # Give it time to reach its BEGIN and wait there.
    waiting.join(timeout=0.3)
    assert waiting.is_alive()
    with contextlib.suppress(StopIteration):
        next(first)
    waiting.join(timeout=5)

    assert seen == [1]
    assert saved_notes() == ["first", "second"]


# ── Read-only sessions ──────────────────────────────────────────────────


def test_a_read_only_session_takes_no_write_lock(notes: None) -> None:
    session = get_read_only_db()
    db = next(session)
    db.execute(text("SELECT count(*) FROM note"))

    writer = other_writer()
    try:
        # A save elsewhere goes ahead while this session reads.
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("ROLLBACK")
    finally:
        writer.close()
        session.close()


def test_a_read_only_session_refuses_any_write(notes: None) -> None:
    session = get_read_only_db()
    db = next(session)
    try:
        with pytest.raises(OperationalError, match="readonly"):
            db.execute(text("INSERT INTO note (body) VALUES ('lost')"))
    finally:
        with contextlib.suppress(StopIteration):
            next(session)

    assert saved_notes() == []


def test_a_read_only_session_hands_its_connection_back_writable(
    notes: None,
) -> None:
    session = get_read_only_db()
    next(session)
    with contextlib.suppress(StopIteration):
        next(session)

    # The pool hands out the same connection next; it must write normally.
    with get_engine().begin() as connection:
        connection.exec_driver_sql("INSERT INTO note (body) VALUES ('kept')")
        assert connection.exec_driver_sql("PRAGMA query_only").scalar() == 0

    assert saved_notes() == ["kept"]


def test_a_read_only_session_leaves_no_pooled_connection_read_only(
    notes: None,
) -> None:
    # Two idle connections in the pool, as when requests run at once. The
    # session must switch query_only off on the connection it switched it
    # on for, not on whichever one the pool hands out next.
    engine = get_engine()
    first, second = engine.connect(), engine.connect()
    first.close()
    second.close()

    session = get_read_only_db()
    next(session)
    with contextlib.suppress(StopIteration):
        next(session)

    held = [engine.connect(), engine.connect()]
    try:
        for connection in held:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar() == 0
    finally:
        for connection in held:
            connection.close()
