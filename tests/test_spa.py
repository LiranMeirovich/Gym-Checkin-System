"""Serving a React build (app.core.spa), on a bare app with a fake build,
so the tests don't need Node or a real ``npm run build``."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.spa import NOT_BUILT_MESSAGE, serve_frontend

INDEX_HTML = '<!doctype html><html lang="he" dir="rtl"><div id="root"></div></html>'
ASSET_JS = "console.log('built');"


def make_client(build_dir: Path) -> TestClient:
    app = FastAPI()

    @app.get("/api/thing")
    def thing() -> dict[str, str]:
        return {"thing": "yes"}

    serve_frontend(app, build_dir)
    return TestClient(app)


@pytest.fixture
def build_dir(tmp_path: Path) -> Path:
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (build / "assets" / "index-abc123.js").write_text(ASSET_JS, encoding="utf-8")
    return build


@pytest.mark.parametrize("path", ["/", "/login", "/customers/42/edit"])
def test_page_addresses_get_index_html(build_dir: Path, path: str) -> None:
    response = make_client(build_dir).get(path)

    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["content-type"].startswith("text/html")


def test_index_html_is_never_cached(build_dir: Path) -> None:
    response = make_client(build_dir).get("/login")

    assert response.headers["cache-control"] == "no-store"


def test_hashed_assets_are_served_and_cached_for_a_year(build_dir: Path) -> None:
    response = make_client(build_dir).get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == ASSET_JS
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_missing_asset_is_404_not_index_html(build_dir: Path) -> None:
    response = make_client(build_dir).get("/assets/index-old.js")

    assert response.status_code == 404


def test_routes_registered_before_win(build_dir: Path) -> None:
    response = make_client(build_dir).get("/api/thing")

    assert response.json() == {"thing": "yes"}


@pytest.mark.parametrize("path", ["/api", "/api/no-such-route", "/api/a/b"])
def test_unknown_api_paths_get_a_json_404(build_dir: Path, path: str) -> None:
    response = make_client(build_dir).get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("path", ["/favicon.ico", "/robots.txt", "/x/y.png"])
def test_file_like_paths_get_a_404(build_dir: Path, path: str) -> None:
    response = make_client(build_dir).get(path)

    assert response.status_code == 404


def test_build_files_outside_assets_are_not_served(build_dir: Path) -> None:
    (build_dir / "secret.txt").write_text("not for you", encoding="utf-8")

    response = make_client(build_dir).get("/secret.txt")

    assert response.status_code == 404


def test_missing_build_gives_503_explaining_it(tmp_path: Path) -> None:
    client = make_client(tmp_path / "not-built")

    page = client.get("/login")
    asset = client.get("/assets/index-abc123.js")

    assert page.status_code == 503
    assert page.text == NOT_BUILT_MESSAGE
    assert asset.status_code == 404
