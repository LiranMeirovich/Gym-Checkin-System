"""Checks that apply in prod only (decision 0050): the public app answers
only to the tunnel's hostname, and the admin app hides FastAPI's API docs."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.admin.main import app as admin_app
from app.public.main import app as public_app
from tests.conftest import THROUGH_THE_TUNNEL, use_prod

ADMIN = "http://127.0.0.1:8000"
DOCS = ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_prod(monkeypatch, tmp_path)


@pytest.fixture
def dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")


@pytest.mark.usefixtures("prod")
@pytest.mark.parametrize(
    "host",
    ["checkin.example.com", "CheckIn.Example.com", "127.0.0.1:8001", "localhost"],
)
def test_prod_public_app_answers_its_hostname_and_local_checks(host: str) -> None:
    client = TestClient(public_app, base_url="https://127.0.0.1:8001")

    response = client.get("/health", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.usefixtures("prod")
@pytest.mark.parametrize(
    "host",
    ["evil.example", "checkin.example.com.evil.example", "www.checkin.example.com"],
)
def test_prod_public_app_refuses_other_hostnames(host: str) -> None:
    client = TestClient(public_app, base_url="https://127.0.0.1:8001")

    response = client.get("/health", headers={"Host": host})

    assert response.status_code == 400


@pytest.mark.usefixtures("prod")
def test_prod_public_app_still_takes_a_tunnel_post() -> None:
    # The Host is checked first; the Origin is then compared with it.
    client = TestClient(public_app, **THROUGH_THE_TUNNEL)

    response = client.post(
        "/health",
        headers={
            "Origin": "https://checkin.example.com",
            "Sec-Fetch-Site": "same-origin",
        },
    )

    assert response.status_code == 405


@pytest.mark.usefixtures("dev")
def test_dev_public_app_answers_any_hostname() -> None:
    client = TestClient(public_app, base_url="http://127.0.0.1:8001")

    response = client.get("/health", headers={"Host": "evil.example"})

    assert response.status_code == 200


@pytest.mark.usefixtures("prod")
@pytest.mark.parametrize("path", DOCS)
def test_prod_admin_app_hides_the_api_docs(path: str) -> None:
    client = TestClient(admin_app, base_url=ADMIN)

    assert client.get(path).status_code == 404


@pytest.mark.usefixtures("dev")
@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_dev_admin_app_keeps_the_api_docs(path: str) -> None:
    client = TestClient(admin_app, base_url=ADMIN)

    assert client.get(path).status_code == 200


@pytest.mark.usefixtures("prod")
def test_prod_still_builds_the_spec_in_process() -> None:
    # The frontend's types come from the app object, not over HTTP.
    assert "/api/session" in admin_app.openapi()["paths"]
