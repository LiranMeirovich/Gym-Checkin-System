"""The monthly report's scheduled job (design doc: "Monthly report"): on or
after the 1st, last month's report is generated and emailed to the manager
without anyone pressing a button.

It isn't a timer for one moment on the 1st. A thread in the admin app runs
``run_due()`` at startup and then every ``CHECK_EVERY`` seconds, and each
run does whatever is due for last month:

1. **Generate** it if it was never generated, by anyone. A month is never
   generated twice by the job; regenerating is the manager's call.
2. **Email the manager** if the newest generation is the job's own and its
   email wasn't sent yet (or failed). A generation the manager made from
   the Reports screen isn't emailed: the manager is looking at it.
3. **Retry the recipients' email** if the manager approved the newest
   generation and sending it failed.

So a PC that was off on the 1st catches up at startup, and an email that
failed while the internet was down goes out within an hour of it coming
back. Most runs find nothing due: a couple of reads. Uvicorn runs one
worker, so there's one thread (CLAUDE.md); the public app never starts it.

The job's generation and emails aren't logged (no staff member did them)
and their rows name no one.
"""

import logging
import threading

from sqlalchemy.orm import Session

from app.core import report_delivery, report_generation
from app.core.db import get_engine
from app.core.models import DeliveryKind
from app.core.months import Month
from app.core.report_delivery import Stage

logger = logging.getLogger(__name__)

# Seconds between runs.
CHECK_EVERY = 60 * 60

# Seconds to wait at shutdown for a run that's under way (a send can take
# up to email.TIMEOUT); the thread is a daemon, so it never blocks exit.
STOP_WAIT = 5

_thread: threading.Thread | None = None
_stop = threading.Event()


def run_due() -> None:
    """Do whatever is due for last month's report, in this thread."""
    month = report_delivery.last_month()
    try:
        current = _status(month)
        if current.stage is Stage.NOT_GENERATED:
            report_generation.generate(month, by=None)
            current = _status(month)
        if current.sending:
            return
        if current.approval is not None:
            if current.failed_email is DeliveryKind.RECIPIENTS_EMAIL:
                report_delivery.retry_failed(month)
            return
        if current.scheduled and (
            current.manager_email is None or not current.manager_email.sent
        ):
            # Only the generation decided on: a regeneration since is the
            # manager's, never emailed.
            report_delivery.email_manager(month, report_id=current.report_id)
    except (
        report_generation.GenerationRunningError,
        report_delivery.SendingError,
    ):
        # The manager started the same work from the screen: next run.
        logger.info("report job for %s: busy, trying again later", month)


def start() -> None:
    """Start the job's thread: a run now, then every ``CHECK_EVERY``
    seconds. The admin app calls it at startup."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="report-schedule", daemon=True)
    _thread.start()


def stop() -> None:
    """Stop the thread at shutdown, waiting briefly for a run under way."""
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(STOP_WAIT)
        _thread = None


def _loop() -> None:
    while not _stop.is_set():
        try:
            run_due()
        except Exception:
            # Never let one bad run end the job: log it and try next time.
            logger.exception("report job failed")
        _stop.wait(CHECK_EVERY)


def _status(month: Month) -> report_delivery.DeliveryStatus:
    with Session(get_engine()) as db, db.begin():
        return report_delivery.status(db, month)
