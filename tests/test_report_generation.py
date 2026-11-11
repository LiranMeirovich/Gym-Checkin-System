"""Generating a month's report (design doc: "Monthly report"): the files and
the snapshot row, the activity log, regenerating, finished months only, one
generation per month at a time, and that the slow part never holds the
write lock. Names and amounts are made up."""

import io
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import months, report_files, report_generation
from app.core.activity_log import Action, Target
from app.core.db import IMMEDIATE, get_engine
from app.core.models import (
    ActivityLogEntry,
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    Report,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.report_generation import (
    EXCEL,
    PDF,
    GenerationRunningError,
    MonthNotFinishedError,
    file_path,
    from_json,
    generate,
    is_generating,
    latest,
    start,
    to_json,
)
from app.core.reports import MonthReport, ReportRow, calculate

NOV = Month(2026, 11)
DEC = Month(2026, 12)
MONTHLY = 25000
FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# Midday on 3 December 2026: November is over.
NOW = datetime(2026, 12, 3, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def december(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(months, "utc_now", lambda: NOW)


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


def add_monthly(db: Session, first: str, last: str, phone: str) -> Customer:
    # A write from a read transaction older than the generation's commit
    # would fail with "database is locked" (WAL), so start a new one.
    db.rollback()
    customer = Customer(
        first_name=first,
        last_name=last,
        phone=phone,
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
            unit_price_agorot=MONTHLY,
            chosen_at=datetime(2026, 11, 2, 10, tzinfo=UTC),
            chosen_by=ChosenBy.CUSTOMER,
        )
    )
    db.commit()
    return customer


@pytest.fixture
def noa(db: Session) -> Customer:
    return add_monthly(db, "Noa", "Levi", "+972501234567")


def fresh(db: Session) -> Session:
    """``db`` with its read transaction ended, so it sees what the
    generation (its own sessions) committed since."""
    db.rollback()
    return db


def saved_report(db: Session, month: Month) -> report_generation.SavedReport | None:
    return latest(fresh(db), month)


def reports(db: Session) -> list[Report]:
    fresh(db)
    return list(db.scalars(select(Report).order_by(Report.id)))


def generation_logs(db: Session) -> list[ActivityLogEntry]:
    fresh(db)
    return list(
        db.scalars(
            select(ActivityLogEntry).where(
                ActivityLogEntry.action == Action.REPORT_GENERATE
            )
        )
    )


# --- A generation ---------------------------------------------------------


def test_generating_saves_both_files_and_the_snapshot(
    db: Session, manager: StaffUser, noa: Customer
) -> None:
    generate(NOV, by=manager)

    saved = saved_report(db, NOV)
    assert saved is not None
    assert saved.report == calculate(db, NOV)
    assert saved.staff_name == "Dana"
    assert saved.generated_at.tzinfo is not None
    assert file_path(NOV, EXCEL) == Path("reports/report-2026-11.xlsx")
    sheet = load_workbook(io.BytesIO(file_path(NOV, EXCEL).read_bytes())).active
    assert sheet["A1"].value == report_files.title(NOV)
    assert sheet["A4"].value == "Noa"
    assert file_path(NOV, PDF).read_bytes().startswith(b"%PDF")
    assert sorted(p.name for p in Path("reports").iterdir()) == [
        "report-2026-11.pdf",
        "report-2026-11.xlsx",
    ]


def test_the_reports_folder_comes_from_the_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db: Session,
    manager: StaffUser,
    noa: Customer,
) -> None:
    monkeypatch.setenv("GYM_REPORTS_DIR", str(tmp_path / "elsewhere"))
    report_generation.get_settings.cache_clear()

    generate(NOV, by=manager)

    assert (tmp_path / "elsewhere" / "report-2026-11.pdf").exists()


def test_a_staff_generation_is_logged(
    db: Session, manager: StaffUser, noa: Customer
) -> None:
    generate(NOV, by=manager)

    (entry,) = generation_logs(db)
    (row,) = reports(db)
    assert entry.staff_user_id == manager.id
    assert entry.target_type == Target.REPORT
    assert entry.target_id == row.id
    assert entry.after_json is not None
    assert '"month": "2026-11"' in entry.after_json
    assert '"total_agorot": 25000' in entry.after_json


def test_the_scheduled_job_names_no_one_and_isnt_logged(
    db: Session, noa: Customer
) -> None:
    generate(NOV, by=None)

    (row,) = reports(db)
    assert row.staff_user_id is None
    assert generation_logs(db) == []
    saved = saved_report(db, NOV)
    assert saved is not None and saved.staff_name is None


def test_regenerating_adds_a_row_and_the_newest_wins(
    db: Session, manager: StaffUser, noa: Customer
) -> None:
    generate(NOV, by=manager)
    add_monthly(db, "Yossi", "Cohen", "+972507654321")

    generate(NOV, by=manager)

    assert len(reports(db)) == 2
    saved = saved_report(db, NOV)
    assert saved is not None
    assert [row.first_name for row in saved.report.rows] == ["Yossi", "Noa"]
    assert len(generation_logs(db)) == 2


def test_an_empty_month_can_be_generated(db: Session, manager: StaffUser) -> None:
    generate(NOV, by=manager)

    saved = saved_report(db, NOV)
    assert saved is not None and saved.report == MonthReport(NOV, ())


def test_a_month_never_generated_has_no_report(db: Session) -> None:
    assert saved_report(db, NOV) is None


# --- Which months, and one at a time ------------------------------------


@pytest.mark.parametrize("month", [DEC, Month(2027, 1)])
def test_the_current_month_and_later_are_refused(
    db: Session, manager: StaffUser, month: Month
) -> None:
    with pytest.raises(MonthNotFinishedError):
        start(month, by=manager)

    assert reports(db) == []


def test_a_second_generation_of_a_month_waits_for_the_first(
    db: Session, manager: StaffUser, noa: Customer
) -> None:
    job = start(NOV, by=manager)
    assert is_generating(NOV)
    with pytest.raises(GenerationRunningError):
        start(NOV, by=manager)
    # Another month isn't held up.
    start(Month(2026, 10), by=manager)()

    job()

    assert not is_generating(NOV)
    generate(NOV, by=manager)
    assert len([r for r in reports(db) if r.month == NOV]) == 2


def test_a_failed_generation_releases_the_month_and_saves_nothing(
    monkeypatch: pytest.MonkeyPatch, db: Session, manager: StaffUser, noa: Customer
) -> None:
    def broken(_report: MonthReport) -> bytes:
        raise OSError("disk full")

    monkeypatch.setattr(report_files, "pdf", broken)

    with pytest.raises(OSError, match="disk full"):
        generate(NOV, by=manager)

    assert not is_generating(NOV)
    assert reports(db) == []
    assert generation_logs(db) == []
    assert not file_path(NOV, PDF).exists()


def test_building_the_files_never_holds_the_write_lock(
    monkeypatch: pytest.MonkeyPatch, db: Session, manager: StaffUser, noa: Customer
) -> None:
    real_excel = report_files.excel

    def excel_while_someone_writes(report: MonthReport) -> bytes:
        # A request's write, as a check-in would make it. If the
        # generation held the write lock, this would wait and then fail
        # with "database is locked".
        engine = get_engine().execution_options(**{IMMEDIATE: True})
        with Session(engine) as other, other.begin():
            other.add(
                Customer(
                    first_name="Maya",
                    last_name="Katz",
                    phone="+972521234567",
                    date_of_birth=date(1995, 1, 1),
                )
            )
        return real_excel(report)

    monkeypatch.setattr(report_files, "excel", excel_while_someone_writes)

    generate(NOV, by=manager)

    assert len(reports(db)) == 1
    assert fresh(db).scalar(select(Customer).where(Customer.first_name == "Maya"))


# --- The snapshot ---------------------------------------------------------


def test_the_snapshot_reads_back_the_same() -> None:
    report = MonthReport(
        NOV,
        (
            ReportRow(1, "דנה", "לוי", (Plan.MONTHLY,), MONTHLY, date(2026, 11, 30)),
            ReportRow(
                2, "Noa", "Katz", (Plan.PUNCH_CARD, Plan.SINGLE_ENTRY), 54000, None
            ),
        ),
    )

    text = to_json(report)

    assert from_json(NOV, text) == report
    assert "דנה" in text  # kept as Hebrew, not \u escapes


def test_an_abandoned_claim_stops_blocking_the_month(
    monkeypatch: pytest.MonkeyPatch, db: Session, manager: StaffUser, noa: Customer
) -> None:
    now = [1000.0]
    monkeypatch.setattr(report_generation.time, "monotonic", lambda: now[0])
    abandoned = start(NOV, by=manager)  # its request failed: never run

    now[0] += report_generation.CLAIM_LIFETIME
    assert not is_generating(NOV)
    newer = start(NOV, by=manager)
    # The abandoned job, run late, leaves the newer claim alone.
    abandoned()
    assert is_generating(NOV)

    newer()
    assert not is_generating(NOV)
    assert len(reports(db)) == 2


def test_a_file_that_cant_be_replaced_leaves_no_partial_file(
    monkeypatch: pytest.MonkeyPatch, db: Session, manager: StaffUser, noa: Customer
) -> None:
    def locked(_source: object, _target: object) -> None:
        raise PermissionError("the file is open in another program")

    monkeypatch.setattr(report_generation.os, "replace", locked)

    with pytest.raises(PermissionError):
        generate(NOV, by=manager)

    assert not Path("reports").exists() or list(Path("reports").iterdir()) == []
    assert reports(db) == []
    assert not is_generating(NOV)
