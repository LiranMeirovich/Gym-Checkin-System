"""Delivering a month's report (design doc: "Monthly report"): the manager's
email, Approve and send, Send again, where the report stands, the refusals,
and that the attachments are the approved generation. Emails are caught by
a fake ``email.send``; names, addresses and amounts are made up."""

import io
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import email, months, report_delivery, report_generation
from app.core.activity_log import Action, Target
from app.core.db import get_engine
from app.core.gym_settings import update_gym_settings
from app.core.models import (
    ActivityLogEntry,
    ChosenBy,
    Customer,
    DeliveryKind,
    Plan,
    PlanChoice,
    ReportDelivery,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.report_delivery import (
    AlreadyApprovedError,
    GenerationRunningError,
    NoRecipientsError,
    NothingToResendError,
    ReportChangedError,
    SendingError,
    Stage,
    email_manager,
    start_approve_and_send,
    start_resend,
    status,
)

NOV = Month(2026, 11)
MONTHLY = 25000
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
NOW = datetime(2026, 12, 1, 0, 5, tzinfo=UTC)
MANAGER = "manager@example.com"
RECIPIENTS = ["accounts@example.com", "owner@example.com"]


@dataclass
class Sent:
    to: tuple[str, ...]
    subject: str
    body: str
    attachments: list[email.Attachment]


class Outbox:
    """Stands in for ``email.send``: keeps what was sent, or fails."""

    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.failing = False

    def send(
        self,
        to: Sequence[str],
        subject: str,
        body: str,
        attachments: Sequence[email.Attachment] = (),
    ) -> None:
        if self.failing:
            raise email.EmailNotSentError(subject)
        self.sent.append(Sent(tuple(to), subject, body, list(attachments)))


@pytest.fixture(autouse=True)
def december(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(months, "utc_now", lambda: NOW)


@pytest.fixture(autouse=True)
def no_claims() -> Iterator[None]:
    yield
    # A failed test may leave a claim behind; the next test starts clean.
    report_delivery._claims.clear()  # noqa: SLF001


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(email, "send", box.send)
    return box


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    member = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH)
    db.add(member)
    db.commit()
    return member


@pytest.fixture
def addresses(db: Session, manager: StaffUser) -> None:
    update_gym_settings(
        db,
        {
            "gym_name": "Example Gym",
            "manager_email": MANAGER,
            "report_recipients": RECIPIENTS,
        },
        by=manager,
    )
    db.commit()


def add_monthly(db: Session, first: str, price: int = MONTHLY) -> None:
    db.rollback()
    customer = Customer(
        first_name=first,
        last_name="Levi",
        phone=f"+97250{abs(hash(first)) % 10_000_000:07d}",
        date_of_birth=date(1990, 5, 1),
    )
    db.add(customer)
    db.flush()
    db.add(
        PlanChoice(
            customer_id=customer.id,
            plan=Plan.MONTHLY,
            start_month=NOV,
            end_month=NOV,
            unit_price_agorot=price,
            chosen_at=datetime(2026, 11, 2, 10, tzinfo=UTC),
            chosen_by=ChosenBy.CUSTOMER,
        )
    )
    db.commit()


@pytest.fixture
def generated(db: Session, manager: StaffUser) -> int:
    """November generated once, with one customer: its report id."""
    add_monthly(db, "Noa")
    report_generation.generate(NOV, by=manager)
    return newest_id(db)


def newest_id(db: Session) -> int:
    db.rollback()
    report_id = status(db, NOV).report_id
    assert report_id is not None
    return report_id


def now(db: Session) -> report_delivery.DeliveryStatus:
    db.rollback()
    return status(db, NOV)


def fresh(db: Session) -> Session:
    """``db`` with its read transaction ended, so it sees what other
    sessions (a generation, a send) committed since, as a request's own
    transaction would."""
    db.rollback()
    return db


def approve(db: Session, manager: StaffUser, report_id: int) -> None:
    """Approve and send, as the route does: commit, then run the job."""
    job = start_approve_and_send(fresh(db), NOV, report_id, by=manager)
    db.commit()
    job()


def resend(db: Session, manager: StaffUser, report_id: int) -> None:
    job = start_resend(fresh(db), NOV, report_id, by=manager)
    db.commit()
    job()


def logs(db: Session, action: Action) -> list[ActivityLogEntry]:
    db.rollback()
    return list(
        db.scalars(select(ActivityLogEntry).where(ActivityLogEntry.action == action))
    )


def names_in(attachment: email.Attachment) -> list[str]:
    sheet = load_workbook(io.BytesIO(attachment.data)).active
    assert sheet is not None
    # The customer rows: every made-up customer here is a Levi.
    return [
        str(row[0]) for row in sheet.iter_rows(values_only=True) if row[1] == "Levi"
    ]


# --- Where it stands --------------------------------------------------------


def test_a_month_never_generated(db: Session) -> None:
    current = status(db, NOV)

    assert current.stage is Stage.NOT_GENERATED
    assert current.report_id is None
    assert current.failed_email is None


@pytest.mark.usefixtures("addresses")
def test_generated_then_emailed_then_approved_and_sent(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    assert now(db).stage is Stage.GENERATED

    email_manager(NOV)
    emailed = now(db)
    assert emailed.stage is Stage.EMAILED
    # The scheduled job names no one.
    assert emailed.manager_email is not None
    assert emailed.manager_email.staff_name is None

    approve(db, manager, generated)
    current = now(db)
    assert current.stage is Stage.SENT
    assert current.approval is not None and current.approval.staff_name == "Dana"
    assert current.recipients_email is not None
    assert current.recipients_email.recipients == tuple(RECIPIENTS)
    assert current.failed_email is None


# --- The manager's email -----------------------------------------------------


@pytest.mark.usefixtures("addresses", "generated")
def test_the_manager_gets_both_files_with_the_gym_name(
    db: Session, outbox: Outbox
) -> None:
    email_manager(NOV)

    (sent,) = outbox.sent
    assert sent.to == (MANAGER,)
    assert sent.subject == "דוח חודשי: נובמבר 2026 – Example Gym"
    assert "אישור ושליחה" in sent.body
    assert [a.filename for a in sent.attachments] == [
        "report-2026-11.xlsx",
        "report-2026-11.pdf",
    ]
    assert sent.attachments[1].data.startswith(b"%PDF")


@pytest.mark.usefixtures("generated")
def test_no_manager_address_is_a_failed_email(db: Session, outbox: Outbox) -> None:
    email_manager(NOV)

    assert outbox.sent == []
    current = now(db)
    assert current.stage is Stage.GENERATED
    assert current.manager_email is not None
    assert current.manager_email.recipients == ()
    assert current.failed_email is DeliveryKind.MANAGER_EMAIL


@pytest.mark.usefixtures("addresses", "generated")
def test_a_failed_manager_email_is_recorded(db: Session, outbox: Outbox) -> None:
    outbox.failing = True

    email_manager(NOV)

    current = now(db)
    assert current.stage is Stage.GENERATED
    assert current.failed_email is DeliveryKind.MANAGER_EMAIL


@pytest.mark.usefixtures("addresses")
def test_nothing_to_email_before_a_generation(db: Session, outbox: Outbox) -> None:
    email_manager(NOV)

    assert outbox.sent == []
    assert now(db).stage is Stage.NOT_GENERATED


@pytest.mark.usefixtures("addresses", "generated")
def test_the_scheduled_email_isnt_logged(db: Session, outbox: Outbox) -> None:
    email_manager(NOV)

    assert logs(db, Action.REPORT_RESEND) == []
    assert logs(db, Action.REPORT_APPROVE_AND_SEND) == []


# --- Approve and send ---------------------------------------------------------


@pytest.mark.usefixtures("addresses")
def test_approving_sends_to_the_recipients_and_logs_it(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    approve(db, manager, generated)

    (sent,) = outbox.sent
    assert sent.to == tuple(RECIPIENTS)
    assert "אישור ושליחה" not in sent.body
    (log,) = logs(db, Action.REPORT_APPROVE_AND_SEND)
    assert log.target_type == Target.REPORT
    assert log.target_id == generated
    assert json.loads(log.after_json or "{}") == {
        "month": "2026-11",
        "recipients": RECIPIENTS,
    }


@pytest.mark.usefixtures("addresses")
def test_a_failed_send_keeps_the_approval(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    outbox.failing = True

    approve(db, manager, generated)

    current = now(db)
    assert current.stage is Stage.APPROVED
    assert current.failed_email is DeliveryKind.RECIPIENTS_EMAIL


@pytest.mark.usefixtures("addresses")
def test_the_attachments_are_the_approved_generation_not_the_files_on_disk(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    # The file on disk is overwritten after the generation was made.
    report_generation.file_path(NOV, report_generation.EXCEL).write_bytes(b"junk")

    approve(db, manager, generated)

    (sent,) = outbox.sent
    assert names_in(sent.attachments[0]) == ["Noa"]


@pytest.mark.usefixtures("addresses")
def test_an_older_generation_cant_be_approved(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    add_monthly(db, "Avi")
    report_generation.generate(NOV, by=manager)

    with pytest.raises(ReportChangedError):
        start_approve_and_send(fresh(db), NOV, generated, by=manager)
    with pytest.raises(ReportChangedError):
        start_approve_and_send(fresh(db), NOV, 999, by=manager)
    assert outbox.sent == []


@pytest.mark.usefixtures("addresses")
def test_a_regeneration_after_approval_starts_unapproved(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    approve(db, manager, generated)
    add_monthly(db, "Avi")
    report_generation.generate(NOV, by=manager)

    current = now(db)
    assert current.report_id != generated
    assert current.stage is Stage.GENERATED
    assert current.approval is None

    approve(db, manager, newest_id(db))
    assert sorted(names_in(outbox.sent[-1].attachments[0])) == ["Avi", "Noa"]


@pytest.mark.usefixtures("addresses")
def test_a_generation_is_approved_once(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    approve(db, manager, generated)

    with pytest.raises(AlreadyApprovedError):
        start_approve_and_send(fresh(db), NOV, generated, by=manager)


def test_no_recipients_refuses_approval(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    with pytest.raises(NoRecipientsError):
        start_approve_and_send(fresh(db), NOV, generated, by=manager)
    db.rollback()
    assert now(db).approval is None


@pytest.mark.usefixtures("addresses")
def test_approval_waits_for_a_running_generation(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    job = report_generation.start(NOV, by=manager)
    try:
        with pytest.raises(GenerationRunningError):
            start_approve_and_send(fresh(db), NOV, generated, by=manager)
    finally:
        job()


@pytest.mark.usefixtures("addresses")
def test_one_email_per_month_at_a_time(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    job = start_approve_and_send(fresh(db), NOV, generated, by=manager)
    db.commit()
    assert now(db).sending

    with pytest.raises(SendingError):
        email_manager(NOV)

    job()
    assert not now(db).sending
    email_manager(NOV)
    assert len(outbox.sent) == 2


@pytest.mark.usefixtures("addresses")
def test_a_claim_is_released_when_the_send_breaks(
    db: Session,
    manager: StaffUser,
    generated: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(email, "send", broken)
    job = start_approve_and_send(fresh(db), NOV, generated, by=manager)
    db.commit()

    with pytest.raises(RuntimeError):
        job()
    assert not report_delivery.is_sending(NOV)


@pytest.mark.usefixtures("addresses")
def test_a_claim_is_released_when_the_approval_cant_be_recorded(
    db: Session,
    manager: StaffUser,
    generated: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("log write failed")

    monkeypatch.setattr(report_delivery, "record", broken)

    with pytest.raises(RuntimeError):
        start_approve_and_send(fresh(db), NOV, generated, by=manager)
    assert not report_delivery.is_sending(NOV)


# --- Send again ------------------------------------------------------------


@pytest.mark.usefixtures("addresses")
def test_resend_sends_the_failed_manager_email(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    outbox.failing = True
    email_manager(NOV)
    outbox.failing = False

    resend(db, manager, generated)

    (sent,) = outbox.sent
    assert sent.to == (MANAGER,)
    current = now(db)
    assert current.stage is Stage.EMAILED
    assert current.manager_email is not None
    assert current.manager_email.staff_name == "Dana"
    (log,) = logs(db, Action.REPORT_RESEND)
    assert json.loads(log.after_json or "{}") == {
        "month": "2026-11",
        "email": "manager_email",
    }


@pytest.mark.usefixtures("addresses")
def test_resend_sends_the_failed_recipients_email(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    outbox.failing = True
    approve(db, manager, generated)
    outbox.failing = False

    resend(db, manager, generated)

    (sent,) = outbox.sent
    assert sent.to == tuple(RECIPIENTS)
    assert now(db).stage is Stage.SENT


@pytest.mark.usefixtures("addresses")
def test_after_approval_only_the_recipients_email_is_resent(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    # The manager's email failed, but the manager approved on the screen.
    outbox.failing = True
    email_manager(NOV)
    outbox.failing = False
    approve(db, manager, generated)

    assert now(db).failed_email is None
    with pytest.raises(NothingToResendError):
        start_resend(fresh(db), NOV, generated, by=manager)


@pytest.mark.usefixtures("addresses")
def test_nothing_to_resend(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    with pytest.raises(NothingToResendError):
        start_resend(fresh(db), NOV, generated, by=manager)
    email_manager(NOV)
    with pytest.raises(NothingToResendError):
        start_resend(fresh(db), NOV, generated, by=manager)


@pytest.mark.usefixtures("addresses")
def test_resend_refuses_an_older_generation(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    outbox.failing = True
    email_manager(NOV)
    report_generation.generate(NOV, by=manager)

    with pytest.raises(ReportChangedError):
        start_resend(fresh(db), NOV, generated, by=manager)


@pytest.mark.usefixtures("addresses")
def test_a_resend_uses_the_recipients_at_the_time(
    db: Session, manager: StaffUser, generated: int, outbox: Outbox
) -> None:
    outbox.failing = True
    approve(db, manager, generated)
    outbox.failing = False
    db.rollback()
    update_gym_settings(db, {"report_recipients": ["new@example.com"]}, by=manager)
    db.commit()

    resend(db, manager, generated)

    assert outbox.sent[-1].to == ("new@example.com",)
    db.rollback()
    rows = db.scalars(
        select(ReportDelivery.recipients_json)
        .where(ReportDelivery.kind == DeliveryKind.RECIPIENTS_EMAIL)
        .order_by(ReportDelivery.id)
    ).all()
    assert [json.loads(r or "[]") for r in rows] == [RECIPIENTS, ["new@example.com"]]
