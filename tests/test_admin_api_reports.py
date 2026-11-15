"""The report routes of the admin JSON API, on the real admin app: who may
use them, the months list, generating (answered 202, done after the
response), the preview, the downloads and the refusals. Names and amounts
are made up."""

import io
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx import Response
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import email, months, pins, report_delivery, report_generation
from app.core.db import get_engine
from app.core.gym_settings import update_gym_settings
from app.core.models import (
    ActivityLogEntry,
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    PunchCard,
    Report,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.punch_cards import expiry_for
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
MONTHLY = 25000
CARD = 50000
# Midday on 3 December 2026: November is the last finished month.
NOW = datetime(2026, 12, 3, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_month(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(months, "utc_now", lambda: NOW)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture
def client(migrated_db: Path) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    staff = create_owner(db, "מנהלת", PIN)
    db.commit()
    return staff


@pytest.fixture
def instructor(db: Session, manager: StaffUser) -> StaffUser:
    staff = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()
    return staff


class Staff:
    """A logged-in browser: sends the CSRF token on every write."""

    def __init__(self, client: TestClient, member: StaffUser) -> None:
        self.client = client
        answer = client.post(
            "/api/login",
            json={"staff_id": member.id, "pin": PIN},
            headers=SAME_ORIGIN,
        )
        assert answer.status_code == 200
        self.headers = {**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]}

    def get(self, path: str):
        return self.client.get(f"/api/reports{path}")

    def generate(self, month: str):
        return self.client.post(f"/api/reports/{month}/generate", headers=self.headers)


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


@pytest.fixture
def customers(db: Session) -> None:
    """Noa Levi on monthly in November; Maya Katz bought a card in October."""
    noa = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1990, 5, 1),
    )
    maya = Customer(
        first_name="Maya",
        last_name="Katz",
        phone="+972507654321",
        date_of_birth=date(1992, 3, 1),
    )
    db.add_all([noa, maya])
    db.flush()
    db.add(
        PlanChoice(
            customer_id=noa.id,
            plan=Plan.MONTHLY,
            start_month=Month(2026, 11),
            end_month=Month(2026, 11),
            unit_price_agorot=MONTHLY,
            chosen_at=datetime(2026, 11, 2, 10, tzinfo=UTC),
            chosen_by=ChosenBy.CUSTOMER,
        )
    )
    db.add(
        PunchCard(
            customer_id=maya.id,
            price_agorot=CARD,
            bought_month=Month(2026, 10),
            expires_on=expiry_for(Month(2026, 10)),
            bought_at=datetime(2026, 10, 20, 10, tzinfo=UTC),
            bought_by=ChosenBy.CUSTOMER,
        )
    )
    db.commit()


def count(db: Session, model: type) -> int:
    db.rollback()
    return db.scalar(select(func.count()).select_from(model)) or 0


# --- Who may use them ----------------------------------------------------


def test_not_logged_in_gets_401(client: TestClient, manager: StaffUser) -> None:
    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/reports/2026-11").status_code == 401
    assert client.get("/api/reports/2026-11/pdf").status_code == 401
    answer = client.post("/api/reports/2026-11/generate", headers=SAME_ORIGIN)
    assert answer.status_code == 401


def test_an_instructor_is_refused_and_nothing_is_generated(
    db: Session, as_instructor: Staff
) -> None:
    assert as_instructor.get("").status_code == 403
    assert as_instructor.generate("2026-11").status_code == 403
    assert count(db, Report) == 0


# --- Months ----------------------------------------------------------------


def test_the_months_run_from_the_first_plan_or_card_to_last_month(
    as_manager: Staff, customers: None
) -> None:
    answer = as_manager.get("")

    assert answer.status_code == 200
    assert answer.json() == {"months": ["2026-11", "2026-10"]}


def test_with_no_data_only_last_month_is_offered(as_manager: Staff) -> None:
    assert as_manager.get("").json() == {"months": ["2026-11"]}


# --- Generating and the preview -----------------------------------------


def test_a_month_never_generated_is_empty(as_manager: Staff) -> None:
    answer = as_manager.get("/2026-11")

    assert answer.status_code == 200
    assert answer.json() == {
        "month": "2026-11",
        "generating": False,
        "generated_at": None,
        "generated_by": None,
        "rows": [],
        "total_agorot": 0,
        "files": False,
        "delivery": {
            "report_id": None,
            "stage": "not_generated",
            "manager_email": None,
            "approval": None,
            "recipients_email": None,
            "failed_email": None,
            "sending": False,
        },
    }


def test_generating_answers_202_then_the_preview_shows_the_snapshot(
    db: Session, as_manager: Staff, customers: None
) -> None:
    answer = as_manager.generate("2026-11")

    assert answer.status_code == 202
    assert answer.json()["generating"] is True
    # TestClient runs the background task before returning.
    preview = as_manager.get("/2026-11").json()
    assert preview["generating"] is False
    assert preview["generated_by"] == "מנהלת"
    assert preview["generated_at"].endswith("+02:00")
    assert preview["rows"] == [
        {
            "first_name": "Maya",
            "last_name": "Katz",
            "plans": ["punch_card"],
            "payment_agorot": 0,
            "ends_on": "2026-11-30",
        },
        {
            "first_name": "Noa",
            "last_name": "Levi",
            "plans": ["monthly"],
            "payment_agorot": MONTHLY,
            "ends_on": "2026-11-30",
        },
    ]
    assert preview["total_agorot"] == MONTHLY
    assert preview["files"] is True
    assert count(db, Report) == 1
    log = db.scalar(select(ActivityLogEntry).order_by(ActivityLogEntry.id.desc()))
    assert log is not None and log.action == "report.generate"


@pytest.mark.parametrize("month", ["2026-12", "2027-01"])
def test_an_unfinished_month_is_refused(
    db: Session, as_manager: Staff, month: str
) -> None:
    answer = as_manager.generate(month)

    assert answer.status_code == 409
    assert answer.json() == {"error": "month_not_finished"}
    assert count(db, Report) == 0


def test_a_month_being_generated_is_refused(
    db: Session, manager: StaffUser, as_manager: Staff
) -> None:
    job = report_generation.start(Month(2026, 11), by=manager)
    try:
        assert as_manager.get("/2026-11").json()["generating"] is True
        answer = as_manager.generate("2026-11")
        assert answer.status_code == 409
        assert answer.json() == {"error": "already_generating"}
    finally:
        job()


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "november", "0999-01"])
def test_a_malformed_month_is_422(as_manager: Staff, month: str) -> None:
    assert as_manager.get(f"/{month}").status_code == 422
    assert as_manager.generate(month).status_code == 422


def test_generating_needs_the_csrf_token(
    db: Session, client: TestClient, as_manager: Staff
) -> None:
    answer = client.post("/api/reports/2026-11/generate", headers=SAME_ORIGIN)

    assert answer.status_code == 403
    assert count(db, Report) == 0


# --- Downloads ------------------------------------------------------------


def test_the_files_download_once_generated(as_manager: Staff, customers: None) -> None:
    assert as_manager.get("/2026-11/excel").status_code == 404
    assert as_manager.get("/2026-11/pdf").status_code == 404
    as_manager.generate("2026-11")

    excel = as_manager.get("/2026-11/excel")
    pdf = as_manager.get("/2026-11/pdf")

    assert excel.status_code == 200
    assert excel.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="report-2026-11.xlsx"' in excel.headers["content-disposition"]
    assert excel.headers["cache-control"] == "no-store"
    sheet = load_workbook(io.BytesIO(excel.content)).active
    assert sheet["A4"].value == "Maya"
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


# --- Delivery: Approve and send, Send again, the dashboard card ------------


RECIPIENTS = ["accounts@example.com", "owner@example.com"]


class FakeSend:
    """Stands in for ``email.send``: keeps the addresses, or fails."""

    def __init__(self) -> None:
        self.to: list[tuple[str, ...]] = []
        self.failing = False

    def __call__(
        self,
        to: Sequence[str],
        subject: str,
        body: str,
        attachments: Sequence[email.Attachment] = (),
    ) -> None:
        if self.failing:
            raise email.EmailNotSentError(subject)
        self.to.append(tuple(to))


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> FakeSend:
    fake = FakeSend()
    monkeypatch.setattr(email, "send", fake)
    return fake


@pytest.fixture(autouse=True)
def no_claims() -> Iterator[None]:
    yield
    report_delivery._claims.clear()  # noqa: SLF001


def set_recipients(db: Session, manager: StaffUser) -> None:
    db.rollback()
    update_gym_settings(
        db,
        {"manager_email": "manager@example.com", "report_recipients": RECIPIENTS},
        by=manager,
    )
    db.commit()


@pytest.fixture
def recipients(db: Session, manager: StaffUser) -> None:
    set_recipients(db, manager)


def approve(staff: Staff, month: str, report_id: object) -> Response:
    return staff.client.post(
        f"/api/reports/{month}/approve",
        json={"report_id": report_id},
        headers=staff.headers,
    )


def resend(staff: Staff, month: str, report_id: object) -> Response:
    return staff.client.post(
        f"/api/reports/{month}/resend",
        json={"report_id": report_id},
        headers=staff.headers,
    )


def refused(answer: Response, code: str) -> None:
    assert answer.status_code == 409
    assert answer.json() == {"error": code}


def generated_id(staff: Staff, month: str = "2026-11") -> int:
    assert staff.generate(month).status_code == 202
    report_id = staff.get(f"/{month}").json()["delivery"]["report_id"]
    assert isinstance(report_id, int)
    return report_id


def last_action(db: Session) -> str | None:
    db.rollback()
    return db.scalar(
        select(ActivityLogEntry.action).order_by(ActivityLogEntry.id.desc())
    )


@pytest.mark.usefixtures("manager")
def test_delivery_routes_need_a_login(client: TestClient) -> None:
    assert client.get("/api/reports/latest").status_code == 401
    for path in ("approve", "resend"):
        answer = client.post(
            f"/api/reports/2026-11/{path}", json={"report_id": 1}, headers=SAME_ORIGIN
        )
        assert answer.status_code == 401


def test_delivery_routes_refuse_an_instructor(as_instructor: Staff) -> None:
    assert as_instructor.get("/latest").status_code == 403
    assert approve(as_instructor, "2026-11", 1).status_code == 403
    assert resend(as_instructor, "2026-11", 1).status_code == 403


@pytest.mark.usefixtures("customers", "recipients")
def test_approve_and_send_answers_202_then_shows_sent(
    db: Session, as_manager: Staff, sent: FakeSend
) -> None:
    report_id = generated_id(as_manager)

    answer = approve(as_manager, "2026-11", report_id)

    assert answer.status_code == 202
    assert answer.json()["delivery"]["approval"]["by"] == "מנהלת"
    assert answer.json()["delivery"]["sending"] is True
    # TestClient runs the background task before returning.
    delivery = as_manager.get("/2026-11").json()["delivery"]
    assert delivery["stage"] == "sent"
    assert delivery["sending"] is False
    assert delivery["recipients_email"]["sent"] is True
    assert delivery["recipients_email"]["recipients"] == RECIPIENTS
    assert delivery["recipients_email"]["by"] == "מנהלת"
    assert delivery["recipients_email"]["at"].endswith("+02:00")
    assert sent.to == [tuple(RECIPIENTS)]
    assert last_action(db) == "report.approve_and_send"


@pytest.mark.usefixtures("customers", "recipients")
def test_a_failed_send_shows_and_send_again_sends_it(
    db: Session, as_manager: Staff, sent: FakeSend
) -> None:
    report_id = generated_id(as_manager)
    sent.failing = True
    approve(as_manager, "2026-11", report_id)

    delivery = as_manager.get("/2026-11").json()["delivery"]
    assert delivery["stage"] == "approved"
    assert delivery["failed_email"] == "recipients_email"

    sent.failing = False
    answer = resend(as_manager, "2026-11", report_id)

    assert answer.status_code == 202
    assert as_manager.get("/2026-11").json()["delivery"]["stage"] == "sent"
    assert last_action(db) == "report.resend"


@pytest.mark.usefixtures("customers")
def test_refusals_are_409_codes_and_record_nothing(
    db: Session, manager: StaffUser, as_manager: Staff, sent: FakeSend
) -> None:
    report_id = generated_id(as_manager)

    refused(approve(as_manager, "2026-11", report_id), "no_recipients")
    refused(resend(as_manager, "2026-11", report_id), "nothing_to_resend")
    refused(approve(as_manager, "2026-11", report_id + 1), "report_changed")
    refused(approve(as_manager, "2026-10", report_id), "report_changed")
    assert last_action(db) == "report.generate"

    set_recipients(db, manager)
    job = report_generation.start(Month(2026, 11), by=manager)
    try:
        refused(approve(as_manager, "2026-11", report_id), "already_generating")
    finally:
        job()
    newer = as_manager.get("/2026-11").json()["delivery"]["report_id"]
    refused(approve(as_manager, "2026-11", report_id), "report_changed")
    assert approve(as_manager, "2026-11", newer).status_code == 202
    refused(approve(as_manager, "2026-11", newer), "already_approved")


@pytest.mark.usefixtures("customers", "recipients")
def test_an_email_going_out_is_already_sending(
    as_manager: Staff, manager: StaffUser, db: Session, sent: FakeSend
) -> None:
    report_id = generated_id(as_manager)
    db.rollback()
    job = report_delivery.start_approve_and_send(
        db, Month(2026, 11), report_id, by=manager
    )
    db.commit()
    try:
        assert as_manager.get("/2026-11").json()["delivery"]["sending"] is True
        refused(resend(as_manager, "2026-11", report_id), "already_sending")
    finally:
        job()


@pytest.mark.parametrize("body", [{}, {"report_id": "one"}, {"report_id": 1, "x": 1}])
def test_a_bad_body_is_422(as_manager: Staff, body: dict[str, object]) -> None:
    for path in ("approve", "resend"):
        answer = as_manager.client.post(
            f"/api/reports/2026-11/{path}", json=body, headers=as_manager.headers
        )
        assert answer.status_code == 422


def test_approving_needs_the_csrf_token(client: TestClient, as_manager: Staff) -> None:
    answer = client.post(
        "/api/reports/2026-11/approve", json={"report_id": 1}, headers=SAME_ORIGIN
    )

    assert answer.status_code == 403


@pytest.mark.usefixtures("customers", "recipients")
def test_the_dashboard_card_shows_last_month(as_manager: Staff, sent: FakeSend) -> None:
    answer = as_manager.get("/latest")
    assert answer.status_code == 200
    assert answer.json()["month"] == "2026-11"
    assert answer.json()["delivery"]["stage"] == "not_generated"

    approve(as_manager, "2026-11", generated_id(as_manager))

    assert as_manager.get("/latest").json()["delivery"]["stage"] == "sent"
