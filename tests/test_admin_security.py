"""Who is making an admin request and whether they may: CurrentStaff,
require_permission and the not-logged-in handling, on a small app with
test-only routes. Names are made up."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import security
from app.admin.csrf import csrf_token
from app.admin.main import app as admin_app
from app.admin.security import (
    SESSION_COOKIE,
    CurrentStaff,
    NotLoggedInError,
    StaffLogin,
    require_permission,
)
from app.core import staff_sessions
from app.core.db import DbSession, get_engine
from app.core.models import StaffSession, StaffUser
from app.core.permissions import Permission, Role
from app.core.staff_sessions import start_session

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
START = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(staff_sessions, "utc_now", clock)
    return clock


def build_app() -> FastAPI:
    app = FastAPI()
    security.install(app)

    @app.get("/who")
    def who(login: CurrentStaff) -> dict[str, str]:
        return {"name": login.staff.display_name}

    @app.get("/prices")
    def prices(
        login: Annotated[
            StaffLogin, Depends(require_permission(Permission.PRICES_EDIT))
        ],
    ) -> dict[str, str]:
        return {"name": login.staff.display_name}

    @app.post("/rename")
    def rename(login: CurrentStaff, db: DbSession) -> dict[str, str]:
        # Same request, same transaction: the dependency's session is
        # the route's session.
        assert db.get(StaffSession, login.session.id) is login.session
        return {}

    return app


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(build_app(), follow_redirects=False) as client:
        yield client


def add_staff(db: Session, name: str, role: Role) -> StaffUser:
    staff = StaffUser(display_name=name, role=role, pin_hash=FAKE_PIN_HASH)
    db.add(staff)
    db.commit()
    return staff


def log_in(db: Session, client: TestClient, staff: StaffUser) -> str:
    token = start_session(db, staff)
    db.commit()
    client.cookies.set(SESSION_COOKIE, token)
    return token


# ── Not logged in ───────────────────────────────────────────────────────


@pytest.fixture
def setup_done(db: Session) -> None:
    """Some staff account exists, so logged-out requests go to the lock
    screen rather than first-run setup."""
    add_staff(db, "Noa", Role.MANAGER)


@pytest.mark.usefixtures("setup_done")
def test_a_page_without_a_session_redirects_to_the_lock_screen(
    client: TestClient,
) -> None:
    response = client.get("/who")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.usefixtures("setup_done")
def test_an_htmx_request_without_a_session_redirects_the_whole_page(
    client: TestClient,
) -> None:
    response = client.get("/who", headers={"HX-Request": "true"})

    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


@pytest.mark.usefixtures("setup_done")
def test_an_unknown_token_is_refused_and_its_cookie_dropped(
    client: TestClient,
) -> None:
    client.cookies.set(SESSION_COOKIE, "made-up-token")

    response = client.get("/who")

    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "Max-Age=0" in cookie


def test_a_permission_check_without_a_session_redirects_too(
    client: TestClient,
) -> None:
    response = client.get("/prices")

    assert response.status_code == 303


def test_before_first_run_setup_every_page_goes_to_setup(
    client: TestClient,
) -> None:
    assert client.get("/who").headers["location"] == "/setup"
    htmx = client.get("/who", headers={"HX-Request": "true"})
    assert htmx.headers["HX-Redirect"] == "/setup"


@pytest.mark.usefixtures("clock")
def test_a_deactivated_staff_member_still_means_setup_is_done(
    db: Session, client: TestClient
) -> None:
    noa = add_staff(db, "Noa", Role.MANAGER)
    noa.active = False
    db.commit()

    assert client.get("/who").headers["location"] == "/login"


# ── Logged in ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("clock")
def test_a_logged_in_request_knows_who_it_is(db: Session, client: TestClient) -> None:
    log_in(db, client, add_staff(db, "Dana", Role.INSTRUCTOR))

    response = client.get("/who")

    assert response.status_code == 200
    assert response.json() == {"name": "Dana"}


@pytest.mark.usefixtures("clock")
def test_the_route_shares_the_dependencys_transaction(
    db: Session, client: TestClient
) -> None:
    token = log_in(db, client, add_staff(db, "Dana", Role.INSTRUCTOR))

    response = client.post("/rename", headers={"X-CSRF-Token": csrf_token(token)})

    assert response.status_code == 200


def test_each_request_counts_as_activity(
    db: Session, client: TestClient, clock: Clock
) -> None:
    log_in(db, client, add_staff(db, "Dana", Role.INSTRUCTOR))

    # Four minutes apart, for longer than the 5-minute lock time.
    for _ in range(3):
        clock.now += timedelta(minutes=4)
        assert client.get("/who").status_code == 200

    db.expire_all()
    session = db.scalars(select(StaffSession)).one()
    assert session.last_seen_at == clock.now


def test_an_idle_session_is_sent_to_the_lock_screen(
    db: Session, client: TestClient, clock: Clock
) -> None:
    log_in(db, client, add_staff(db, "Dana", Role.INSTRUCTOR))

    clock.now += timedelta(minutes=6)

    assert client.get("/who").status_code == 303


@pytest.mark.usefixtures("clock")
def test_deactivation_applies_from_the_next_request(
    db: Session, client: TestClient
) -> None:
    dana = add_staff(db, "Dana", Role.INSTRUCTOR)
    log_in(db, client, dana)
    assert client.get("/who").status_code == 200

    dana.active = False
    db.commit()

    assert client.get("/who").status_code == 303


# ── Permissions ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("clock")
def test_a_manager_has_a_manager_permission(db: Session, client: TestClient) -> None:
    log_in(db, client, add_staff(db, "Noa", Role.MANAGER))

    assert client.get("/prices").status_code == 200


@pytest.mark.usefixtures("clock")
def test_an_instructor_is_refused_a_manager_permission(
    db: Session, client: TestClient
) -> None:
    log_in(db, client, add_staff(db, "Dana", Role.INSTRUCTOR))

    assert client.get("/prices").status_code == 403


@pytest.mark.usefixtures("clock")
def test_a_role_change_applies_from_the_next_request(
    db: Session, client: TestClient
) -> None:
    noa = add_staff(db, "Noa", Role.MANAGER)
    add_staff(db, "Tal", Role.MANAGER)
    log_in(db, client, noa)
    assert client.get("/prices").status_code == 200

    noa.role = Role.INSTRUCTOR
    db.commit()

    assert client.get("/prices").status_code == 403


def test_an_unknown_permission_is_refused_when_the_route_is_defined() -> None:
    with pytest.raises(ValueError):
        require_permission("prices.edti")  # type: ignore[arg-type]


def test_the_admin_app_sends_logged_out_requests_to_the_lock_screen() -> None:
    assert NotLoggedInError in admin_app.exception_handlers
