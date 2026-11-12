"""Sending an email with attachments: the monthly report to the manager and
to the recipients (design doc: "Monthly report").

The message is built with the standard library's ``email`` package, which
encodes Hebrew subjects and file names and refuses a header with a line
break in it (no injected headers or recipients). The addresses come from
the gym's settings, which are validated when saved.

Where it goes depends on the deployment config:

- **SMTP** (``GYM_SMTP_HOST`` set, always in prod): STARTTLS with the
  system's certificate checks, then the app password, with a time limit on
  the connection. Any failure raises ``EmailNotSentError``; its cause goes
  to the server log (never the password, which only ``smtplib`` sees).
- **The outbox** (dev without SMTP): the message is written as a ``.eml``
  file to ``OUTBOX``, to open in a mail program, and counts as sent. Prod
  can't get here: it refuses to start without SMTP.

Sending can take seconds, so callers run it outside a request's
transaction (decision 0027).
"""

import logging
import smtplib
import ssl
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from app.core.clock import utc_now
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Dev only: where emails are saved instead of sent. Relative to the folder
# the app is started from, like the reports folder; git-ignored.
OUTBOX = Path("outbox")

# Seconds to wait on the mail server before giving up on this attempt.
TIMEOUT = 30

# The From address of an outbox email, where no SMTP user is set.
OUTBOX_SENDER = "gym@localhost"


class EmailNotSentError(RuntimeError):
    """The email couldn't be sent. The cause is in the server log."""


@dataclass(frozen=True)
class Attachment:
    filename: str
    data: bytes
    # The MIME type, e.g. "application/pdf".
    content_type: str


def send(
    to: Sequence[str],
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
) -> None:
    """Send one email to every address in ``to``, or in dev without SMTP,
    save it to the outbox. Raises ``EmailNotSentError``."""
    if not to:
        raise ValueError("an email needs at least one address")
    settings = get_settings()
    message = build(
        sender=settings.smtp_user or OUTBOX_SENDER,
        to=to,
        subject=subject,
        body=body,
        attachments=attachments,
    )
    if not settings.sends_email:
        _save_to_outbox(message)
        return
    host, user, password = (
        settings.smtp_host,
        settings.smtp_user,
        settings.smtp_password,
    )
    if host is None or user is None or password is None:
        # Config refuses a partial set-up, so this never happens.
        raise RuntimeError("SMTP is only partly set up")
    try:
        with smtplib.SMTP(host, settings.smtp_port, timeout=TIMEOUT) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, password.get_secret_value())
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        # The class and message only: smtplib's errors hold the server's
        # reply, never the password.
        logger.warning(
            "email %r not sent: %s: %s", subject, type(error).__name__, error
        )
        raise EmailNotSentError(str(subject)) from error


def build(
    *,
    sender: str,
    to: Sequence[str],
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
) -> EmailMessage:
    """The message ``send()`` sends. Raises ``ValueError`` for a header
    value with a line break in it."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    message.set_content(body)
    for attachment in attachments:
        maintype, subtype = attachment.content_type.split("/", 1)
        message.add_attachment(
            attachment.data,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    return message


def _save_to_outbox(message: EmailMessage) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y-%m-%dT%H-%M-%S")
    path = OUTBOX / f"{stamp}-{uuid.uuid4().hex[:8]}.eml"
    path.write_bytes(message.as_bytes())
    logger.info("email %r saved to %s (no SMTP set up)", message["Subject"], path)
