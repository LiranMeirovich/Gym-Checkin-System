"""Delivering a month's report: emailing it to the manager, the manager's
approval, and emailing it to the recipients (design doc: "Monthly report").

Every step is a ``report_deliveries`` row naming one generation (a
``reports`` row), never a change to it. Only a month's newest generation
is delivered: a regeneration is a new generation with no steps, so it
starts unapproved, and an action on the generation the manager was looking
at is refused once a newer one exists (``ReportChangedError``).

- **The manager's email** is sent by the scheduled job only (``by=None``),
  to ``manager_email`` in the gym settings. With no address set, it's a
  failed email with no addresses, retried once one is.
- **Approve and send** records the approval (and logs it) in the caller's
  transaction, then returns the job that emails the recipients in the gym
  settings.
- **Send again** resends the email that failed: the recipients' once the
  generation is approved, the manager's before that.

Sending can take seconds, so it runs outside any request's transaction
(decision 0027), as a generation does: it reads in a plain ``BEGIN``,
sends, then records the outcome in one short ``BEGIN IMMEDIATE``
transaction. One send per month runs at a time (a claim in this process,
like ``report_generation``'s, abandoned after ``CLAIM_LIFETIME``).

The attachments are built from the generation's snapshot in memory, not
read from the reports folder, so an email carries exactly the generation
that was approved, whatever the files on disk hold by then.
"""

import enum
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import email, report_files, report_generation
from app.core.activity_log import Action, Target, record
from app.core.db import IMMEDIATE, get_engine
from app.core.gym_settings import load_gym_settings
from app.core.models import (
    DeliveryKind,
    EmailOutcome,
    Report,
    ReportDelivery,
    StaffUser,
)
from app.core.months import Month

logger = logging.getLogger(__name__)

# A send takes at most a few times email.TIMEOUT; a claim this old was
# abandoned.
CLAIM_LIFETIME = 10 * 60

_EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PDF_TYPE = "application/pdf"

# Each month with an email going out: the claim's token and when it was
# made (``time.monotonic()``).
_claims: dict[Month, tuple[object, float]] = {}
_claims_guard = threading.Lock()


class Stage(enum.StrEnum):
    """Where a month's report stands, in order."""

    NOT_GENERATED = "not_generated"
    GENERATED = "generated"
    EMAILED = "emailed"
    APPROVED = "approved"
    SENT = "sent"


class ReportChangedError(ValueError):
    """The generation isn't the month's newest (or doesn't exist)."""


class GenerationRunningError(RuntimeError):
    """The month is being generated: a newer generation is on its way."""


class SendingError(RuntimeError):
    """An email for this month is going out already."""


class AlreadyApprovedError(ValueError):
    """This generation was approved already."""


class NoRecipientsError(ValueError):
    """The gym settings list no report recipients."""


class NothingToResendError(ValueError):
    """The generation's last email didn't fail."""


@dataclass(frozen=True)
class EmailStep:
    at: datetime
    sent: bool
    # The addresses it went to (none when no manager address was set).
    recipients: tuple[str, ...]
    # Who started it; ``None`` for the scheduled job.
    staff_name: str | None


@dataclass(frozen=True)
class ApprovalStep:
    at: datetime
    staff_name: str


@dataclass(frozen=True)
class DeliveryStatus:
    """A month's newest generation and the newest step of each kind for
    it. All ``None`` (and ``report_id`` too) when it was never generated."""

    month: Month
    report_id: int | None
    # The scheduled job made the generation (nobody pressed Generate).
    scheduled: bool
    manager_email: EmailStep | None
    approval: ApprovalStep | None
    recipients_email: EmailStep | None
    # An email for the month is going out now.
    sending: bool

    @property
    def stage(self) -> Stage:
        if self.report_id is None:
            return Stage.NOT_GENERATED
        if self.recipients_email is not None and self.recipients_email.sent:
            return Stage.SENT
        if self.approval is not None:
            return Stage.APPROVED
        if self.manager_email is not None and self.manager_email.sent:
            return Stage.EMAILED
        return Stage.GENERATED

    @property
    def failed_email(self) -> DeliveryKind | None:
        """The email to send again: the recipients' once approved, the
        manager's before that, if its newest attempt failed."""
        step, kind = (
            (self.recipients_email, DeliveryKind.RECIPIENTS_EMAIL)
            if self.approval is not None
            else (self.manager_email, DeliveryKind.MANAGER_EMAIL)
        )
        if step is None or step.sent:
            return None
        return kind


def status(db: Session, month: Month) -> DeliveryStatus:
    """Where ``month``'s report stands. Only reads."""
    newest_report = db.scalar(
        select(Report).where(Report.month == month).order_by(Report.id.desc()).limit(1)
    )
    if newest_report is None:
        return DeliveryStatus(
            month, None, False, None, None, None, sending=is_sending(month)
        )
    report_id = newest_report.id
    newest: dict[DeliveryKind, ReportDelivery] = {}
    for step in db.scalars(
        select(ReportDelivery)
        .where(ReportDelivery.report_id == report_id)
        .order_by(ReportDelivery.id)
    ):
        newest[step.kind] = step
    approval = newest.get(DeliveryKind.APPROVAL)
    return DeliveryStatus(
        month=month,
        report_id=report_id,
        scheduled=newest_report.staff_user_id is None,
        manager_email=_email_step(newest.get(DeliveryKind.MANAGER_EMAIL)),
        approval=None
        if approval is None or approval.staff is None
        else ApprovalStep(approval.at, approval.staff.display_name),
        recipients_email=_email_step(newest.get(DeliveryKind.RECIPIENTS_EMAIL)),
        sending=is_sending(month),
    )


def email_manager(month: Month) -> None:
    """Email ``month``'s newest generation to the manager now, in this
    thread (the scheduled job). Does nothing if it was never generated.
    A failure is recorded, not raised. Raises ``SendingError``."""
    with Session(get_engine()) as db, db.begin():
        report_id = _newest_report_id(db, month)
    if report_id is None:
        return
    token = _claim(month)
    _send_job(month, report_id, DeliveryKind.MANAGER_EMAIL, None, token)()


def start_approve_and_send(
    db: Session, month: Month, report_id: int, *, by: StaffUser
) -> Callable[[], None]:
    """Approve generation ``report_id`` of ``month`` and return the job that
    emails it to the recipients. The approval and its log entry are added in
    ``db``'s transaction; the job runs after it commits.

    Raises ``ReportChangedError``, ``GenerationRunningError``,
    ``SendingError``, ``AlreadyApprovedError`` or ``NoRecipientsError``.
    """
    _check_newest(db, month, report_id)
    current = status(db, month)
    if current.approval is not None:
        raise AlreadyApprovedError(f"report {report_id} is approved already")
    recipients = load_gym_settings(db).report_recipients
    if not recipients:
        raise NoRecipientsError("no report recipients in the settings")
    token = _claim(month)
    try:
        db.add(
            ReportDelivery(
                report_id=report_id, kind=DeliveryKind.APPROVAL, staff_user_id=by.id
            )
        )
        record(
            db,
            by,
            Action.REPORT_APPROVE_AND_SEND,
            Target.REPORT,
            report_id,
            after={"month": str(month), "recipients": list(recipients)},
        )
        db.flush()
    except BaseException:
        _release(month, token)
        raise
    return _send_job(month, report_id, DeliveryKind.RECIPIENTS_EMAIL, by.id, token)


def start_resend(
    db: Session, month: Month, report_id: int, *, by: StaffUser
) -> Callable[[], None]:
    """Return the job that sends generation ``report_id``'s failed email
    again, and log it in ``db``'s transaction.

    Raises ``ReportChangedError``, ``GenerationRunningError``,
    ``SendingError`` or ``NothingToResendError``.
    """
    _check_newest(db, month, report_id)
    kind = status(db, month).failed_email
    if kind is None:
        raise NothingToResendError(f"report {report_id} has no failed email")
    token = _claim(month)
    try:
        record(
            db,
            by,
            Action.REPORT_RESEND,
            Target.REPORT,
            report_id,
            after={"month": str(month), "email": str(kind)},
        )
        db.flush()
    except BaseException:
        _release(month, token)
        raise
    return _send_job(month, report_id, kind, by.id, token)


def retry_failed(month: Month) -> None:
    """Send ``month``'s failed email again now, in this thread (the
    scheduled job): not logged, the row names no one. Does nothing if no
    email failed. Raises ``SendingError``."""
    with Session(get_engine()) as db, db.begin():
        current = status(db, month)
    kind = current.failed_email
    if kind is None or current.report_id is None:
        return
    token = _claim(month)
    _send_job(month, current.report_id, kind, None, token)()


def is_sending(month: Month) -> bool:
    with _claims_guard:
        return _is_claimed(month)


def subject(month: Month, gym_name: str | None) -> str:
    """ "דוח חודשי: אוקטובר 2026 – <gym name>"."""
    title = report_files.title(month)
    return title if gym_name is None else f"{title} – {gym_name}"


def body(month: Month, kind: DeliveryKind) -> str:
    title = report_files.title(month)
    if kind is DeliveryKind.MANAGER_EMAIL:
        return (
            f"{title} מצורף (Excel ו-PDF).\n\n"
            "יש לבדוק אותו במסך הדוחות במערכת. אם הוא תקין, לחצו שם"
            ' על "אישור ושליחה" והוא יישלח לנמענים שבהגדרות.\n'
        )
    return f"{title} מצורף (Excel ו-PDF).\n"


# --- Inside ----------------------------------------------------------------


def _check_newest(db: Session, month: Month, report_id: int) -> None:
    if report_generation.is_generating(month):
        raise GenerationRunningError(f"{month} is being generated")
    if _newest_report_id(db, month) != report_id:
        raise ReportChangedError(f"report {report_id} isn't {month}'s newest")


def _newest_report_id(db: Session, month: Month) -> int | None:
    return db.scalar(
        select(Report.id)
        .where(Report.month == month)
        .order_by(Report.id.desc())
        .limit(1)
    )


def _email_step(row: ReportDelivery | None) -> EmailStep | None:
    if row is None:
        return None
    return EmailStep(
        at=row.at,
        sent=row.outcome is EmailOutcome.SENT,
        recipients=tuple(json.loads(row.recipients_json or "[]")),
        staff_name=None if row.staff is None else row.staff.display_name,
    )


def _claim(month: Month) -> object:
    token = object()
    with _claims_guard:
        if _is_claimed(month):
            raise SendingError(f"an email for {month} is going out")
        _claims[month] = (token, time.monotonic())
    return token


def _is_claimed(month: Month) -> bool:
    # The caller holds ``_claims_guard``.
    claim = _claims.get(month)
    return claim is not None and time.monotonic() - claim[1] < CLAIM_LIFETIME


def _send_job(
    month: Month,
    report_id: int,
    kind: DeliveryKind,
    staff_id: int | None,
    token: object,
) -> Callable[[], None]:
    return partial(_send, month, report_id, kind, staff_id, token)


def _send(
    month: Month,
    report_id: int,
    kind: DeliveryKind,
    staff_id: int | None,
    token: object,
) -> None:
    try:
        with Session(get_engine()) as db, db.begin():
            row = db.get_one(Report, report_id)
            report = report_generation.from_json(month, row.rows_json)
            settings = load_gym_settings(db)
        to: Sequence[str] = (
            () if settings.manager_email is None else (settings.manager_email,)
        )
        if kind is DeliveryKind.RECIPIENTS_EMAIL:
            to = settings.report_recipients
        sent = False
        if not to:
            logger.warning("report %s not emailed: no address in the settings", month)
        else:
            try:
                email.send(
                    to,
                    subject(month, settings.gym_name),
                    body(month, kind),
                    [
                        email.Attachment(
                            report_files.file_name(month, report_generation.EXCEL),
                            report_files.excel(report),
                            _EXCEL_TYPE,
                        ),
                        email.Attachment(
                            report_files.file_name(month, report_generation.PDF),
                            report_files.pdf(report),
                            _PDF_TYPE,
                        ),
                    ],
                )
                sent = True
            except email.EmailNotSentError:
                pass  # Logged by email.send(); recorded as failed below.
        _record(report_id, kind, sent, to, staff_id)
    finally:
        _release(month, token)


def _release(month: Month, token: object) -> None:
    with _claims_guard:
        # Only this claim: if it was abandoned and the month claimed again,
        # the newer send keeps its claim (see report_generation._generate).
        if _claims.get(month, (None, 0.0))[0] is token:
            del _claims[month]


def _record(
    report_id: int,
    kind: DeliveryKind,
    sent: bool,
    to: Sequence[str],
    staff_id: int | None,
) -> None:
    engine = get_engine().execution_options(**{IMMEDIATE: True})
    with Session(engine) as db, db.begin():
        db.add(
            ReportDelivery(
                report_id=report_id,
                kind=kind,
                outcome=EmailOutcome.SENT if sent else EmailOutcome.FAILED,
                recipients_json=json.dumps(list(to), ensure_ascii=False),
                staff_user_id=staff_id,
            )
        )
