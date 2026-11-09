"""Smoke tests: both apps start and answer, and the public app exposes
nothing beyond what it should."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin.main import app as admin_app
from app.core.http import ACCESS_LOGGER, DropQueryStrings
from app.core.spa import FRONTEND_DIST
from app.public.main import app as public_app

both_apps = pytest.mark.parametrize(
    "app", [admin_app, public_app], ids=["admin", "public"]
)


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_health_returns_ok(app: FastAPI) -> None:
    # The `with` block runs the app's startup: the config and database checks.
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_the_access_log_drops_query_strings(app: FastAPI) -> None:
    access = logging.getLogger(ACCESS_LOGGER)
    for installed in [f for f in access.filters if isinstance(f, DropQueryStrings)]:
        access.removeFilter(installed)

    # Starting twice (as both apps share the logger) installs it once.
    for _ in range(2):
        with TestClient(app, base_url="http://127.0.0.1:8000"):
            pass

    assert sum(isinstance(f, DropQueryStrings) for f in access.filters) == 1
    # uvicorn's own access record.
    record = logging.LogRecord(
        ACCESS_LOGGER,
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/customers?q=Noa%20Levi&page=2", "1.1", 200),
        None,
    )
    assert access.filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "GET /api/customers HTTP/1.1" 200'


@both_apps
def test_app_refuses_to_start_on_invalid_config(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_TIMEZONE", "Not/A_Zone")

    with pytest.raises(ValidationError, match="timezone"), TestClient(app):
        pass


def test_public_app_registers_only_expected_routes() -> None:
    # An allowlist: any new public route (or FastAPI's auto-generated docs)
    # fails this test until it's added here on purpose.
    # FastAPI keeps each included router as one entry without a path, so
    # the API routes are read from the OpenAPI spec; none of them may be
    # left out of it, or it could hide from this list.
    included = [route for route in public_app.routes if not hasattr(route, "path")]
    assert all(
        route.include_in_schema
        for router in included
        for route in router.original_router.routes
    )
    paths = set(public_app.openapi()["paths"]) | {
        route.path for route in public_app.routes if hasattr(route, "path")
    }

    # /assets and the catch-all serve the public React build (app.core.spa).
    assert paths == {
        "/health",
        "/api/branding",
        "/branding/logo",
        "/api/check-in",
        "/api/health-form",
        "/api/link",
        "/api/me",
        "/api/sign-up",
        "/assets",
        "/{path:path}",
    }


def test_each_app_serves_its_own_frontend_build() -> None:
    # The public app is reachable from the internet: it must never serve
    # the admin build.
    assert admin_app.state.frontend_dir == FRONTEND_DIST / "admin"
    assert public_app.state.frontend_dir == FRONTEND_DIST / "public"


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_frontend_catch_all_comes_after_the_apps_own_routes(app: FastAPI) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        health = client.get("/health")
        unknown_api = client.get("/api/no-such-route")

    assert health.json() == {"status": "ok"}
    assert unknown_api.status_code == 404
    assert unknown_api.headers["content-type"] == "application/json"


@pytest.mark.usefixtures("migrated_db")
@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000"])
def test_admin_app_answers_on_local_names(host: str) -> None:
    with TestClient(admin_app, base_url=f"http://{host}") as client:
        response = client.get("/health")

    assert response.status_code == 200


@pytest.mark.usefixtures("migrated_db")
@pytest.mark.parametrize(
    "host", ["evil.example", "127.0.0.1.evil.example", "192.168.1.10:8000"]
)
def test_admin_app_refuses_other_host_names(host: str) -> None:
    # DNS rebinding: a website pointed at 127.0.0.1 still sends its own name.
    with TestClient(admin_app, base_url=f"http://{host}") as client:
        response = client.get("/health")

    assert response.status_code == 400


@pytest.mark.parametrize("build", ["admin", "public"])
def test_both_react_apps_are_hebrew_right_to_left(build: str) -> None:
    index_html = FRONTEND_DIST.parent / "src" / build / "index.html"

    assert '<html lang="he" dir="rtl">' in index_html.read_text(encoding="utf-8")


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_both_apps_refuse_cross_site_posts(app: FastAPI) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        refused = client.post("/health", headers={"Origin": "https://evil.example"})
        own = client.post("/health", headers={"Origin": "http://127.0.0.1:8000"})

    # Refused before routing (403); the app's own origin reaches the router,
    # which has no POST /health (405).
    assert refused.status_code == 403
    assert own.status_code == 405


@both_apps
@pytest.mark.usefixtures("migrated_db")
def test_both_apps_never_cache_api_answers(app: FastAPI) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/api/no-such-route")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.usefixtures("migrated_db")
def test_the_public_origin_check_matches_the_tunnels_https() -> None:
    # Behind cloudflared, uvicorn takes the scheme from X-Forwarded-Proto,
    # so the request URL is https and matches the phone's Origin.
    with TestClient(public_app, base_url="https://checkin.example.com") as client:
        response = client.post(
            "/health",
            headers={
                "Origin": "https://checkin.example.com",
                "Sec-Fetch-Site": "same-origin",
            },
        )

    assert response.status_code == 405
