"""CSRF protection on the admin app: the same-origin check on every unsafe
request, and the signed per-session token on logged-in ones. Names are
made up."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.admin import security
from app.admin.csrf import SameOriginMiddleware, csrf_token, csrf_token_matches
from app.admin.main import app as admin_app
from app.admin.security import SESSION_COOKIE, CurrentStaff
from app.core import staff_sessions
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.models import StaffUser
from app.core.permissions import Role
from app.core.staff_sessions import start_session

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(staff_sessions, "utc_now", lambda: now)


class Note(BaseModel):
    text: str


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SameOriginMiddleware)
    security.install(app)

    @app.post("/open")
    def open_form() -> dict[str, str]:
        # No session needed, like the lock screen: only the origin check.
        return {}

    @app.get("/page")
    def page(login: CurrentStaff) -> dict[str, str]:
        return {}

    @app.post("/note")
    def note(login: CurrentStaff, body: Note) -> dict[str, str]:
        return {"text": body.text}

    @app.delete("/note")
    def delete_note(login: CurrentStaff) -> dict[str, str]:
        return {}

    return app


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(build_app(), base_url=ORIGIN, follow_redirects=False) as client:
        yield client


def with_token(token: str) -> dict[str, str]:
    return {**SAME_ORIGIN, "X-CSRF-Token": token}


def log_in(db: Session, client: TestClient, name: str = "Dana") -> str:
    staff = StaffUser(display_name=name, role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH)
    db.add(staff)
    db.flush()
    token = start_session(db, staff)
    db.commit()
    client.cookies.set(SESSION_COOKIE, token)
    return token


# ── Layer 1: same origin ────────────────────────────────────────────────


def test_a_post_from_this_app_is_let_through(client: TestClient) -> None:
    assert client.post("/open", headers=SAME_ORIGIN).status_code == 200


def test_a_post_with_origin_but_no_fetch_metadata_is_let_through(
    client: TestClient,
) -> None:
    # Older browsers send Origin but not Sec-Fetch-Site.
    assert client.post("/open", headers={"Origin": ORIGIN}).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "same-origin"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost:8000"},
        {"Origin": "http://127.0.0.1:8001"},
        {"Origin": "https://127.0.0.1:8000"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "same-site"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "none"},
    ],
    ids=[
        "no-headers",
        "no-origin",
        "other-site",
        "null-origin",
        "other-name",
        "public-app-port",
        "other-scheme",
        "cross-site",
        "same-site",
        "typed-in",
    ],
)
def test_a_post_from_anywhere_else_is_refused(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post("/open", headers=headers)

    assert response.status_code == 403


def test_the_origin_check_runs_before_the_session_check(
    db: Session, client: TestClient
) -> None:
    token = log_in(db, client)

    response = client.post(
        "/note",
        json={"text": "hi"},
        headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf_token(token)},
    )

    assert response.status_code == 403


def test_a_get_needs_no_origin(db: Session, client: TestClient) -> None:
    log_in(db, client)

    assert client.get("/page").status_code == 200


# ── Layer 2: the session's token ────────────────────────────────────────


def test_a_request_with_the_sessions_token_is_accepted(
    db: Session, client: TestClient
) -> None:
    token = log_in(db, client)

    response = client.post(
        "/note", json={"text": "שלום"}, headers=with_token(csrf_token(token))
    )

    assert response.status_code == 200
    assert response.json() == {"text": "שלום"}


def test_a_delete_with_the_sessions_token_is_accepted(
    db: Session, client: TestClient
) -> None:
    token = log_in(db, client)

    response = client.delete("/note", headers=with_token(csrf_token(token)))

    assert response.status_code == 200


@pytest.mark.parametrize("submitted", [None, "", "0" * 64, "not-a-token"], ids=str)
def test_a_logged_in_post_without_the_right_token_is_refused(
    db: Session, client: TestClient, submitted: str | None
) -> None:
    log_in(db, client)
    headers = SAME_ORIGIN if submitted is None else with_token(submitted)

    response = client.post("/note", json={"text": "hi"}, headers=headers)

    assert response.status_code == 403


def test_a_token_in_a_form_field_is_not_accepted(
    db: Session, client: TestClient
) -> None:
    # Only the header counts since the HTML forms are gone: one way in.
    token = log_in(db, client)

    response = client.post(
        "/note", data={"csrf_token": csrf_token(token)}, headers=SAME_ORIGIN
    )

    assert response.status_code == 403


def test_another_sessions_token_is_refused(db: Session, client: TestClient) -> None:
    other = log_in(db, client, "Noa")
    log_in(db, client, "Dana")

    response = client.post(
        "/note", json={"text": "hi"}, headers=with_token(csrf_token(other))
    )

    assert response.status_code == 403


def test_the_session_token_itself_is_not_the_csrf_token(
    db: Session, client: TestClient
) -> None:
    token = log_in(db, client)

    response = client.post("/note", json={"text": "hi"}, headers=with_token(token))

    assert response.status_code == 403


def test_a_post_without_a_session_is_a_401(client: TestClient) -> None:
    response = client.post("/note", json={"text": "hi"}, headers=SAME_ORIGIN)

    assert response.status_code == 401


# ── The token itself ────────────────────────────────────────────────────


def test_the_token_depends_on_the_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_SECRET_KEY", "a" * 40)
    get_settings.cache_clear()
    first = csrf_token("session-token")

    monkeypatch.setenv("GYM_SECRET_KEY", "b" * 40)
    get_settings.cache_clear()

    assert csrf_token("session-token") != first
    assert not csrf_token_matches("session-token", first)


def test_the_token_is_a_sha256_hex_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    token = csrf_token("session-token")

    assert len(token) == 64
    assert int(token, 16) >= 0


# ── Wiring ──────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("migrated_db")
def test_the_admin_app_refuses_cross_site_posts() -> None:
    with TestClient(admin_app, base_url=ORIGIN) as client:
        response = client.post("/health", headers={"Origin": "https://evil.example"})

    # Refused before routing: not 405 (no POST /health), but 403.
    assert response.status_code == 403
