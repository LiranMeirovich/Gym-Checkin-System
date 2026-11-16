"""Security headers on every answer of both apps (decision 0050)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.main import app as admin_app
from app.core.http import (
    SECURITY_HEADERS,
    STRICT_TRANSPORT_SECURITY,
    SecurityHeadersMiddleware,
)
from app.core.spa import serve_frontend
from app.public.main import app as public_app
from tests.conftest import use_prod

ORIGIN = "http://127.0.0.1:8000"

both_apps = pytest.mark.parametrize(
    "app", [admin_app, public_app], ids=["admin", "public"]
)


def assert_security_headers(headers: dict[str, str] | object) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert headers[name] == value  # type: ignore[index]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A small app with a route, an error and a built frontend."""
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text("<!doctype html><title>t</title>")
    (build / "assets" / "app-abc123.js").write_text("console.log(1)")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    serve_frontend(app, build)
    return TestClient(app, base_url=ORIGIN)


@pytest.mark.parametrize("path", ["/api/thing", "/", "/assets/app-abc123.js"])
def test_every_answer_gets_the_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    response = client.get(path)

    assert response.status_code == 200
    assert_security_headers(response.headers)


@pytest.mark.parametrize("path", ["/api/nothing", "/favicon.ico"])
def test_errors_get_the_headers_too(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    response = client.get(path)

    assert response.status_code == 404
    assert_security_headers(response.headers)


def test_the_policy_allows_only_this_origin() -> None:
    policy = dict(
        part.split(" ", 1)
        for part in SECURITY_HEADERS["Content-Security-Policy"].split("; ")
    )

    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == "'self'"
    assert policy["style-src"] == "'self'"
    assert policy["object-src"] == "'none'"
    assert policy["frame-ancestors"] == "'none'"
    assert "unsafe" not in SECURITY_HEADERS["Content-Security-Policy"]


def test_dev_sends_no_hsts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    assert "Strict-Transport-Security" not in client.get("/api/thing").headers


def test_prod_sends_hsts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_prod(monkeypatch, tmp_path)

    response = client.get("/api/thing")

    assert response.headers["Strict-Transport-Security"] == STRICT_TRANSPORT_SECURITY
    assert_security_headers(response.headers)


@both_apps
def test_both_apps_send_them_on_a_refused_post(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same-origin check refuses before any route runs; the headers
    # still wrap its answer.
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    client = TestClient(app, base_url=ORIGIN)

    response = client.post("/api/anything", headers={"Origin": "http://evil.example"})

    assert response.status_code == 403
    assert_security_headers(response.headers)


def test_the_admin_apps_host_refusal_gets_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    client = TestClient(admin_app, base_url=ORIGIN)

    response = client.get("/health", headers={"Host": "evil.example"})

    assert response.status_code == 400
    assert_security_headers(response.headers)
