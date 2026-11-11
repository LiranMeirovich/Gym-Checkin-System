"""Every manager-only admin route refuses an instructor (decision 0037).

``MANAGER_ONLY`` is written out by hand, so adding a route is a deliberate
step: each feature adds its manager-only routes here. A second test reads
the permission each route actually declares and fails if the list is
missing one (or names one that isn't manager-only any more), so a route
can't be forgotten. Names are made up.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import pins
from app.core.db import get_engine
from app.core.http import API_PREFIX
from app.core.permissions import ROLE_PERMISSIONS, Permission, Role
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"

# (method, path) of every route an instructor may not use.
MANAGER_ONLY = {
    ("PUT", "/api/customers/{customer_id}/date-of-birth"),
    ("POST", "/api/customers/{customer_id}/deactivate"),
    ("POST", "/api/prices"),
    ("POST", "/api/customers/{customer_id}/plan"),
    ("POST", "/api/customers/{customer_id}/plan/corrections"),
    ("GET", "/api/customers/{customer_id}/health-forms"),
    ("POST", "/api/customers/{customer_id}/health-forms/{form_id}/open"),
    ("POST", "/api/customers/{customer_id}/doctor-notes/{note_id}/open"),
    ("POST", "/api/customers/{customer_id}/health-form/accept"),
    ("GET", "/api/health-forms/needing-note"),
    ("GET", "/api/staff"),
    ("POST", "/api/staff"),
    ("PUT", "/api/staff/{staff_id}/pin"),
    ("PUT", "/api/staff/{staff_id}/role"),
    ("POST", "/api/staff/{staff_id}/deactivate"),
    ("POST", "/api/staff/{staff_id}/reactivate"),
    ("GET", "/api/activity-log"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/reports"),
    ("GET", "/api/reports/{month}"),
    ("POST", "/api/reports/{month}/generate"),
    ("GET", "/api/reports/{month}/excel"),
    ("GET", "/api/reports/{month}/pdf"),
}


def api_routes() -> Iterator[APIRoute]:
    # FastAPI keeps each included router as one entry without a path.
    for included in app.routes:
        if not hasattr(included, "path"):
            yield from included.original_router.routes


def permissions_of(dependant: Dependant) -> set[Permission]:
    """The permissions a route's dependencies check, at any depth
    (``require_permission`` tags its check with the permission)."""
    found: set[Permission] = set()
    for sub in dependant.dependencies:
        permission = getattr(sub.call, "permission", None)
        if permission is not None:
            found.add(permission)
        found |= permissions_of(sub)
    return found


def test_the_list_matches_what_the_routes_declare() -> None:
    instructor_may = ROLE_PERMISSIONS[Role.INSTRUCTOR]
    declared = {
        (method, API_PREFIX + route.path)
        for route in api_routes()
        if permissions_of(route.dependant) - instructor_may
        for method in route.methods
    }

    assert declared == MANAGER_ONLY


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture
def as_instructor(migrated_db: Path) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with Session(get_engine()) as db:
        manager = create_owner(db, "מנהלת", PIN)
        instructor = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
        db.commit()
        instructor_id = instructor.id
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        answer = client.post(
            "/api/login",
            json={"staff_id": instructor_id, "pin": PIN},
            headers=SAME_ORIGIN,
        )
        assert answer.status_code == 200
        headers = {**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]}
        yield client, headers


@pytest.mark.parametrize(("method", "path"), sorted(MANAGER_ONLY), ids=" ".join)
def test_an_instructor_is_refused(
    as_instructor: tuple[TestClient, dict[str, str]], method: str, path: str
) -> None:
    client, headers = as_instructor
    # Ids of things that don't exist and an empty body: the permission
    # check comes first, so the answer is a 403, not a 404 or a 422.
    url = path.format(customer_id=1, form_id=1, note_id=1, staff_id=1, month="2026-11")
    answer = client.request(method, url, headers=headers, json={})

    assert answer.status_code == 403
