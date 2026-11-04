"""The public app's health form routes: the form for a linked phone,
signing it, and the status ``/api/me`` reports. Names and answers are made
up."""

import base64
import io
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import health_forms
from app.core.db import get_engine
from app.core.health_forms import CURRENT_VERSION, FORMS
from app.core.models import Customer, HealthForm, StaffUser
from app.core.permissions import Role
from app.core.phone_links import issue_link_code
from app.public.device import DEVICE_COOKIE
from app.public.main import app as public_app

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
ORIGIN = "https://checkin.example.com"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
ALL_NO = {q.key: False for q in FORMS[CURRENT_VERSION].questions}
# Noon in Israel on 4 November 2026.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


def signature_data_url(*, drawn: bool = True) -> str:
    image = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    if drawn:
        ImageDraw.Draw(image).line([(20, 100), (100, 30), (180, 90)], "black", 5)
    out = io.BytesIO()
    image.save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


SIGNATURE = signature_data_url()


def form(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "version": CURRENT_VERSION,
        "answers": ALL_NO,
        "details": {},
        "gender": "female",
        "signer_name": "Noa Levi",
        "confirmed": True,
        "signature": SIGNATURE,
    }
    return fields | changes


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_forms, "utc_now", lambda: NOW)


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    with TestClient(public_app, base_url=ORIGIN) as client:
        yield client


@pytest.fixture
def customer(db: Session) -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1995, 5, 17),
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def linked(client: TestClient, db: Session, customer: Customer) -> TestClient:
    """The client, as a phone linked to ``customer``."""
    staff = StaffUser(display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH)
    db.add(staff)
    db.commit()
    code = issue_link_code(db, customer, by=staff).code
    db.commit()
    response = client.post(
        "/api/link",
        json={"phone": "0501234567", "code": code},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 200
    return client


def sign(client: TestClient, **changes: object):
    return client.post("/api/health-form", json=form(**changes), headers=SAME_ORIGIN)


# ── Not linked ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_phone_that_isnt_linked_gets_401(client: TestClient, method: str) -> None:
    response = client.get("/api/health-form") if method == "get" else sign(client)

    assert response.status_code == 401
    assert response.json() == {"detail": "not_linked"}


def test_a_dead_cookie_is_dropped(client: TestClient) -> None:
    client.cookies.set(DEVICE_COOKIE, "made-up-token")

    response = client.get("/api/health-form")

    assert response.status_code == 401
    assert DEVICE_COOKIE in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_another_site_cant_sign_for_the_phone(linked: TestClient) -> None:
    response = linked.post(
        "/api/health-form",
        json=form(),
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


# ── The form ───────────────────────────────────────────────────────────


def test_a_linked_phone_gets_the_current_form(linked: TestClient) -> None:
    response = linked.get("/api/health-form")

    assert response.status_code == 200
    page = response.json()
    assert page["version"] == CURRENT_VERSION
    assert page["customer_name"] == "Noa Levi"
    assert page["date_of_birth"] == "1995-05-17"
    assert page["phone"] == "050-1234567"
    assert [q["key"] for q in page["questions"]] == list(ALL_NO)
    assert page["guardian_consent"] is None
    assert page["valid_until_if_signed"] == "2027-11-03"
    assert response.headers["cache-control"] == "no-store"


def test_an_under_18_gets_the_parents_consent(
    linked: TestClient, db: Session, customer: Customer
) -> None:
    customer.date_of_birth = date(2010, 5, 1)
    db.commit()

    page = linked.get("/api/health-form").json()

    assert "Noa Levi" in page["guardian_consent"]


# ── Signing ────────────────────────────────────────────────────────────


def test_no_form_yet_shows_as_missing(linked: TestClient) -> None:
    me = linked.get("/api/me").json()

    assert me["health_form"] == {"state": "missing", "valid_until": None}


def test_signing_makes_the_form_valid(linked: TestClient, db: Session) -> None:
    response = sign(linked)

    assert response.status_code == 200
    assert response.json() == {"state": "valid", "valid_until": "2027-11-03"}
    assert linked.get("/api/me").json()["health_form"]["state"] == "valid"
    saved = db.scalars(select(HealthForm)).one()
    assert saved.signed_on == date(2026, 11, 4)
    assert saved.document.startswith(b"%PDF-")


def test_a_yes_answer_needs_a_doctors_note(linked: TestClient, db: Session) -> None:
    response = sign(
        linked,
        answers=ALL_NO | {"other": True},
        details={"other": "made-up detail"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "needs_doctor_note"
    saved = db.scalars(select(HealthForm)).one()
    assert json.loads(saved.answers_json)["details"] == {"other": "made-up detail"}


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"answers": {}}, "answers"),
        ({"gender": "x"}, "gender"),
        ({"signer_name": ""}, "signer_name"),
        ({"confirmed": False}, "confirmed"),
        ({"signature": signature_data_url(drawn=False)}, "signature"),
        ({"signature": "data:image/png;base64,not base64!"}, "signature"),
        ({"signature": "data:image/jpeg;base64,AAAA"}, "signature"),
    ],
    ids=[
        "no answers",
        "unknown gender",
        "no name",
        "not confirmed",
        "blank signature",
        "broken base64",
        "not a png data url",
    ],
)
def test_a_bad_field_is_refused(
    linked: TestClient, db: Session, changes: dict[str, object], field: str
) -> None:
    response = sign(linked, **changes)

    assert response.status_code == 400
    assert response.json() == {"errors": {field: "invalid"}}
    assert db.scalars(select(HealthForm)).first() is None


@pytest.mark.parametrize(
    "changes",
    [{"answers": ALL_NO | {"stroke": "true"}}, {"confirmed": "yes"}],
    ids=["answer as text", "confirmed as text"],
)
def test_answers_must_be_real_booleans(
    linked: TestClient, changes: dict[str, object]
) -> None:
    assert sign(linked, **changes).status_code == 422


def test_an_old_version_gets_409(linked: TestClient, db: Session) -> None:
    response = sign(linked, version="2020-01")

    assert response.status_code == 409
    assert response.json() == {"detail": "form_version_changed"}
    assert db.scalars(select(HealthForm)).first() is None


def test_an_oversized_signature_is_refused_before_decoding(linked: TestClient) -> None:
    huge = "data:image/png;base64," + "A" * 500_000

    assert sign(linked, signature=huge).status_code == 422


@pytest.mark.parametrize(
    "details",
    [{"other": "x" * 1001}, {"k" * 51: "x"}],
    ids=["long value", "long key"],
)
def test_oversized_details_are_refused_before_checking(
    linked: TestClient, details: dict[str, str]
) -> None:
    assert sign(linked, details=details).status_code == 422
