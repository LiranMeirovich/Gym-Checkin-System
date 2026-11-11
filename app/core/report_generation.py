"""Generating a month's report: calculating it, saving its snapshot and its
Excel and PDF files, and reading the newest generation back (design doc:
"Monthly report"; follow-up: keep slow work out of a request's
transaction, decision 0027).

A generation runs outside any request's transaction, in three parts:

1. **Read**: ``app.core.reports.calculate()`` in a plain ``BEGIN``
   transaction of its own. In WAL mode that's a consistent snapshot that
   never takes the write lock, so check-ins carry on meanwhile.
2. **Files**: the Excel file and the PDF, written to the reports folder
   (``GYM_REPORTS_DIR``) under a temporary name and then moved into place,
   so a half-written file is never what's downloaded or emailed.
3. **Record**: one short ``BEGIN IMMEDIATE`` transaction adds the
   ``reports`` row (the snapshot as JSON) and, for a staff member's
   generation, the activity log entry.

The preview and the files come from the same snapshot. The newest row for a
month is its report; regenerating adds a row (the table is append-only).

Only finished months can be generated: the current month isn't over. One
generation per month runs at a time (the apps run a single worker, so a
lock in this process is enough); a second is refused while the first runs.
"""

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import report_files
from app.core.activity_log import Action, Target, record
from app.core.config import get_settings
from app.core.db import IMMEDIATE, get_engine
from app.core.models import Plan, PlanChoice, PunchCard, Report, StaffUser
from app.core.months import Month
from app.core.reports import MonthReport, ReportRow, calculate

EXCEL = "xlsx"
PDF = "pdf"

_running: set[Month] = set()
_running_guard = threading.Lock()


class MonthNotFinishedError(ValueError):
    """The month is the current one or later: its report isn't ready."""


class GenerationRunningError(RuntimeError):
    """This month's report is being generated already."""


@dataclass(frozen=True)
class SavedReport:
    """A month's newest generation."""

    report: MonthReport
    generated_at: datetime
    # Who generated it; ``None`` when the scheduled job did.
    staff_name: str | None


def start(month: Month, *, by: StaffUser | None) -> Callable[[], None]:
    """Claim ``month`` for a generation and return the job that runs it,
    for a background task (staff member ``by``) or the scheduled job
    (``None``). The job releases the claim when it ends, whether or not it
    succeeds.

    Raises ``MonthNotFinishedError`` or ``GenerationRunningError``.
    """
    if month >= Month.current():
        raise MonthNotFinishedError(f"{month} isn't over yet")
    with _running_guard:
        if month in _running:
            raise GenerationRunningError(f"{month} is being generated")
        _running.add(month)
    return partial(_generate, month, None if by is None else by.id)


def generate(month: Month, *, by: StaffUser | None) -> None:
    """Generate ``month``'s report now, in this thread. Raises what
    ``start()`` raises."""
    start(month, by=by)()


def report_months(db: Session) -> list[Month]:
    """The months a report can be opened for, newest first: every finished
    month from the first one with a plan choice or a punch card, or just
    last month when there's none yet. Only reads."""
    last = Month.current().plus(-1)
    starts = [
        db.scalar(select(func.min(PlanChoice.start_month))),
        db.scalar(select(func.min(PunchCard.bought_month))),
    ]
    first = min((m for m in starts if m is not None), default=last)
    months = []
    month = last
    while month >= first:
        months.append(month)
        month = month.plus(-1)
    return months or [last]


def is_generating(month: Month) -> bool:
    with _running_guard:
        return month in _running


def latest(db: Session, month: Month) -> SavedReport | None:
    """``month``'s newest generation, or ``None`` if it was never
    generated. Only reads."""
    row = db.scalar(
        select(Report).where(Report.month == month).order_by(Report.id.desc()).limit(1)
    )
    if row is None:
        return None
    return SavedReport(
        report=from_json(month, row.rows_json),
        generated_at=row.generated_at,
        staff_name=None if row.staff is None else row.staff.display_name,
    )


def file_path(month: Month, extension: str) -> Path:
    """Where ``month``'s Excel (``xlsx``) or PDF (``pdf``) file is saved."""
    return get_settings().reports_dir / report_files.file_name(month, extension)


def to_json(report: MonthReport) -> str:
    """The snapshot ``reports.rows_json`` holds."""
    return json.dumps(
        [
            {
                "customer_id": row.customer_id,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "plans": [str(plan) for plan in row.plans],
                "payment_agorot": row.payment_agorot,
                "ends_on": None if row.ends_on is None else row.ends_on.isoformat(),
            }
            for row in report.rows
        ],
        ensure_ascii=False,
    )


def from_json(month: Month, text: str) -> MonthReport:
    """The report a ``to_json()`` snapshot holds."""
    return MonthReport(
        month,
        tuple(
            ReportRow(
                customer_id=row["customer_id"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                plans=tuple(Plan(plan) for plan in row["plans"]),
                payment_agorot=row["payment_agorot"],
                ends_on=None
                if row["ends_on"] is None
                else date.fromisoformat(row["ends_on"]),
            )
            for row in json.loads(text)
        ),
    )


def _generate(month: Month, staff_id: int | None) -> None:
    try:
        with Session(get_engine()) as db, db.begin():
            report = calculate(db, month)
        _save(file_path(month, EXCEL), report_files.excel(report))
        _save(file_path(month, PDF), report_files.pdf(report))
        _record(report, staff_id)
    finally:
        with _running_guard:
            _running.discard(month)


def _save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = path.with_name(path.name + ".partial")
    partial_path.write_bytes(data)
    os.replace(partial_path, path)


def _record(report: MonthReport, staff_id: int | None) -> None:
    engine = get_engine().execution_options(**{IMMEDIATE: True})
    with Session(engine) as db, db.begin():
        row = Report(
            month=report.month, staff_user_id=staff_id, rows_json=to_json(report)
        )
        db.add(row)
        db.flush()
        if staff_id is None:
            return
        staff = db.get_one(StaffUser, staff_id)
        record(
            db,
            staff,
            Action.REPORT_GENERATE,
            Target.REPORT,
            row.id,
            after={
                "month": str(report.month),
                "rows": len(report.rows),
                "total_agorot": report.total_agorot,
            },
        )
