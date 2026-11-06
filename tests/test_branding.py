"""The gym's logo and name on both apps (app.core.branding, decision 0034).

Each test points the app at a branding folder of its own, so the
developer's real ``branding/logo.jpg`` is never read."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.main import app as admin_app
from app.core.branding import BRANDING_DIR
from app.core.db import get_engine
from app.core.gym_settings import update_gym_settings
from app.core.models import StaffUser
from app.core.permissions import Role
from app.public.main import app as public_app

both_apps = pytest.mark.parametrize(
    "app", [admin_app, public_app], ids=["admin", "public"]
)

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# Not a real JPEG: the route sends the file as it is.
FAKE_JPEG = b"\xff\xd8\xff\xe0 made-up logo bytes"


@pytest.fixture
def branding_dir(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "branding"
    folder.mkdir()
    saved = admin_app.state.branding_dir, public_app.state.branding_dir
    admin_app.state.branding_dir = public_app.state.branding_dir = folder
    yield folder
    admin_app.state.branding_dir, public_app.state.branding_dir = saved


@pytest.fixture
def client(app: FastAPI, migrated_db: Path) -> Iterator[TestClient]:
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def set_gym_name(name: str) -> None:
    with Session(get_engine()) as db:
        manager = StaffUser(
            display_name="Noa", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH
        )
        db.add(manager)
        db.flush()
        update_gym_settings(db, {"gym_name": name}, by=manager)
        db.commit()


def test_both_apps_read_the_projects_branding_folder() -> None:
    assert admin_app.state.branding_dir == BRANDING_DIR
    assert public_app.state.branding_dir == BRANDING_DIR
    assert BRANDING_DIR.name == "branding"


@both_apps
def test_the_logo_is_served_without_a_login(
    client: TestClient, branding_dir: Path
) -> None:
    (branding_dir / "logo.jpg").write_bytes(FAKE_JPEG)

    response = client.get("/branding/logo")

    assert response.status_code == 200
    assert response.content == FAKE_JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    # The browser checks back each time, so a replaced logo shows at once.
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" in response.headers


@both_apps
def test_a_missing_logo_is_a_404_not_the_react_page(
    client: TestClient, branding_dir: Path
) -> None:
    response = client.get("/branding/logo")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


@both_apps
def test_only_logo_jpg_is_served(client: TestClient, branding_dir: Path) -> None:
    (branding_dir / "logo.png").write_bytes(b"not this one")

    assert client.get("/branding/logo").status_code == 404


@both_apps
def test_branding_before_setup_has_no_name_and_no_logo(
    client: TestClient, branding_dir: Path
) -> None:
    response = client.get("/api/branding")

    assert response.status_code == 200
    assert response.json() == {"gym_name": None, "has_logo": False}
    assert response.headers["cache-control"] == "no-store"


@both_apps
def test_branding_gives_the_gym_name_and_says_there_is_a_logo(
    client: TestClient, branding_dir: Path
) -> None:
    set_gym_name("מכון הדוגמה")
    (branding_dir / "logo.jpg").write_bytes(FAKE_JPEG)

    response = client.get("/api/branding")

    assert response.json() == {"gym_name": "מכון הדוגמה", "has_logo": True}
