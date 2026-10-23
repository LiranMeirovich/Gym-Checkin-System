"""Smoke tests: both apps start and answer, and the public app exposes
nothing beyond what it should."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.main import app as admin_app
from app.public.main import app as public_app


@pytest.mark.parametrize("app", [admin_app, public_app], ids=["admin", "public"])
def test_health_returns_ok(app: FastAPI) -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_app_registers_only_expected_routes() -> None:
    # An allowlist: any new public route (or FastAPI's auto-generated docs)
    # fails this test until it's added here on purpose.
    paths = {route.path for route in public_app.routes}

    assert paths == {"/health"}
