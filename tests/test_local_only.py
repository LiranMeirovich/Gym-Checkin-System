"""Both apps serve only requests that arrive on the loopback address, even
if started on 0.0.0.0 (decision 0050)."""

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.main import app as admin_app
from app.core.http import LocalOnlyMiddleware
from app.public.main import app as public_app

both_apps = pytest.mark.parametrize(
    "app", [admin_app, public_app], ids=["admin", "public"]
)


@pytest.fixture(autouse=True)
def dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")


def small_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LocalOnlyMiddleware)

    @app.get("/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    return app


@pytest.mark.parametrize(
    "address", ["192.168.1.10", "10.0.0.5", "203.0.113.7", "[2001:db8::1]"]
)
def test_a_request_arriving_on_another_address_is_refused(address: str) -> None:
    # The TestClient makes the URL's host the address the request arrived
    # on, as uvicorn does with the socket's own address.
    client = TestClient(small_app(), base_url=f"http://{address}:8000")

    response = client.get("/thing", headers={"Host": "127.0.0.1:8000"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "127.0.0.2", "[::1]", "[::ffff:127.0.0.1]"]
)
def test_loopback_addresses_are_served(address: str) -> None:
    client = TestClient(small_app(), base_url=f"http://{address}:8000")

    assert client.get("/thing").status_code == 200


def test_a_name_instead_of_an_address_is_refused() -> None:
    # uvicorn always gives an address; anything else is not trusted.
    client = TestClient(small_app(), base_url="http://testserver")

    assert client.get("/thing").status_code == 403


def test_a_unix_socket_is_served() -> None:
    # A Unix socket has no address (scope["server"] is None) and only local
    # processes can connect to it.
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/thing",
        "raw_path": b"/thing",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"localhost")],
        "client": None,
        "server": None,
    }
    asyncio.run(small_app()(scope, receive, send))  # type: ignore[arg-type]

    assert sent[0]["status"] == 200


def test_a_refusal_is_logged_with_the_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(small_app(), base_url="http://192.168.1.10:8000")

    with caplog.at_level(logging.ERROR, logger="app.core.http"):
        client.get("/thing")

    assert "192.168.1.10" in caplog.text
    assert "127.0.0.1" in caplog.text


@both_apps
def test_both_apps_refuse_a_request_off_loopback(app: FastAPI) -> None:
    # Started on 0.0.0.0, the app is reached on the gym network's address.
    client = TestClient(app, base_url="http://192.168.1.10:8000")

    response = client.get("/health", headers={"Host": "127.0.0.1:8000"})

    assert response.status_code == 403
    assert response.text == "Served on 127.0.0.1 only"


def test_each_address_is_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    # A flood of requests can't flood the log.
    app = small_app()
    on_lan = TestClient(app, base_url="http://192.168.1.10:8000")
    on_other = TestClient(app, base_url="http://10.0.0.5:8000")

    with caplog.at_level(logging.ERROR, logger="app.core.http"):
        for _ in range(3):
            assert on_lan.get("/thing").status_code == 403
        assert on_other.get("/thing").status_code == 403

    assert [r.args for r in caplog.records] == [("192.168.1.10",), ("10.0.0.5",)]
