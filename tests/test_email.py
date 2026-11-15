"""Sending an email: the message itself, SMTP with STARTTLS (against a fake
server), failures, and the dev outbox. Addresses are made up."""

import email
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import default
from pathlib import Path
from typing import Any

import pytest

from app.core import email as mail
from app.core.config import get_settings

PDF = mail.Attachment("report-2026-10.pdf", b"%PDF-1.4 fake", "application/pdf")
EXCEL = mail.Attachment(
    "report-2026-10.xlsx",
    b"PK fake",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
SUBJECT = "דוח חודשי – אוקטובר 2026 – חדר כושר לדוגמה"


class FakeSMTP:
    """Stands in for ``smtplib.SMTP`` and records what the code asked of it,
    in order."""

    instances: list["FakeSMTP"] = []
    fail_at: str | None = None

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.calls: list[tuple[str, Any]] = [("connect", (host, port, timeout))]
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, step: str) -> None:
        if FakeSMTP.fail_at == step:
            if step == "connect":
                raise ConnectionRefusedError("no route")
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append(("quit", None))

    def starttls(self, context: ssl.SSLContext) -> None:
        self.calls.append(("starttls", context))
        self._maybe_fail("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", (user, password)))
        self._maybe_fail("login")

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append(("send", message))
        self._maybe_fail("send")


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GYM_SMTP_USER", "gym@example.com")
    monkeypatch.setenv("GYM_SMTP_PASSWORD", "not-a-real-password")
    get_settings.cache_clear()
    FakeSMTP.instances = []
    FakeSMTP.fail_at = None
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def no_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    get_settings.cache_clear()

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("no SMTP connection without a host")

    monkeypatch.setattr(mail.smtplib, "SMTP", refuse)


def send_report() -> None:
    mail.send(
        ["manager@example.com", "accounts@example.com"],
        SUBJECT,
        "הדוח החודשי מצורף.",
        [EXCEL, PDF],
    )


def test_the_message_has_its_headers_body_and_attachments() -> None:
    message = mail.build(
        sender="gym@example.com",
        to=["manager@example.com", "accounts@example.com"],
        subject=SUBJECT,
        body="הדוח החודשי מצורף.",
        attachments=[EXCEL, PDF],
    )
    # Read back from the bytes that go on the wire.
    parsed = email.message_from_bytes(message.as_bytes(), policy=default)

    assert parsed["From"] == "gym@example.com"
    assert parsed["To"] == "manager@example.com, accounts@example.com"
    assert parsed["Subject"] == SUBJECT
    assert parsed["Date"] and parsed["Message-ID"].endswith("@example.com>")
    assert parsed.get_body().get_content().strip() == "הדוח החודשי מצורף."
    files = [
        (part.get_filename(), part.get_content_type(), part.get_content())
        for part in parsed.iter_attachments()
    ]
    assert files == [
        (EXCEL.filename, EXCEL.content_type, EXCEL.data),
        (PDF.filename, PDF.content_type, PDF.data),
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject", "October\r\nBcc: someone@example.com"),
        ("to", ["manager@example.com\nBcc: someone@example.com"]),
    ],
)
def test_a_line_break_in_a_header_is_refused(field: str, value: object) -> None:
    fields: dict[str, Any] = {
        "sender": "gym@example.com",
        "to": ["manager@example.com"],
        "subject": "October",
        "body": "body",
        field: value,
    }

    with pytest.raises(ValueError):
        mail.build(**fields)


def test_smtp_starts_tls_with_certificate_checks_before_logging_in(
    smtp: type[FakeSMTP],
) -> None:
    send_report()

    (server,) = smtp.instances
    steps = [name for name, _ in server.calls]
    assert steps == ["connect", "starttls", "login", "send", "quit"]
    assert server.calls[0][1] == ("smtp.example.com", 587, mail.TIMEOUT)
    context = server.calls[1][1]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert server.calls[2][1] == ("gym@example.com", "not-a-real-password")
    sent = server.calls[3][1]
    assert sent["To"] == "manager@example.com, accounts@example.com"
    assert sent["From"] == "gym@example.com"


@pytest.mark.parametrize("step", ["connect", "starttls", "login", "send"])
def test_a_failure_at_any_step_is_email_not_sent(
    smtp: type[FakeSMTP], step: str, caplog: pytest.LogCaptureFixture
) -> None:
    smtp.fail_at = step

    with pytest.raises(mail.EmailNotSentError):
        send_report()

    assert "not sent" in caplog.text
    assert "not-a-real-password" not in caplog.text


def test_a_timeout_is_email_not_sent(
    smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(self: FakeSMTP, message: EmailMessage) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(FakeSMTP, "send_message", slow)

    with pytest.raises(mail.EmailNotSentError):
        send_report()


@pytest.mark.usefixtures("no_smtp")
def test_without_smtp_the_email_is_saved_to_the_outbox(isolated_env: Path) -> None:
    send_report()

    (saved,) = (isolated_env / "outbox").glob("*.eml")
    parsed = email.message_from_bytes(saved.read_bytes(), policy=default)
    assert parsed["From"] == mail.OUTBOX_SENDER
    assert parsed["Subject"] == SUBJECT
    assert [part.get_filename() for part in parsed.iter_attachments()] == [
        EXCEL.filename,
        PDF.filename,
    ]


@pytest.mark.usefixtures("no_smtp")
def test_each_outbox_email_is_its_own_file(isolated_env: Path) -> None:
    send_report()
    send_report()

    assert len(list((isolated_env / "outbox").glob("*.eml"))) == 2


@pytest.mark.usefixtures("no_smtp")
def test_an_email_needs_an_address() -> None:
    with pytest.raises(ValueError):
        mail.send([], SUBJECT, "body")
