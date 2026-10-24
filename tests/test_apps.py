"""Smoke tests: both apps start and answer, and the public app exposes
nothing beyond what it should."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin.main import app as admin_app
from app.public.main import app as public_app

both_apps = pytest.mark.parametrize(
    "app", [admin_app, public_app], ids=["admin", "public"]
)


@both_apps
def test_health_returns_ok(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    # The `with` block runs the app's startup, including the config check.
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
    paths = {route.path for route in public_app.routes}

    assert paths == {"/health"}
