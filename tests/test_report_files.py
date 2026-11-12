"""A month's report as Excel and PDF: the file names, the Hebrew title and
plan names, the workbook's cells (right to left, exact amounts, real dates,
the total) and that the PDF renders, across pages too. Names and amounts
are made up."""

import io
import re
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook

from app.core.models import Plan
from app.core.months import Month
from app.core.report_files import (
    HEADINGS,
    TOTAL,
    excel,
    file_name,
    pdf,
    plan_names,
    title,
)
from app.core.reports import MonthReport, ReportRow

NOV = Month(2026, 11)
ROWS = (
    ReportRow(1, "דנה", "לוי", (Plan.MONTHLY,), 25000, date(2026, 11, 30)),
    ReportRow(2, "יוסי", "כהן", (Plan.SINGLE_ENTRY,), 12000, None),
    ReportRow(
        3, "מאיה", "כץ", (Plan.PUNCH_CARD, Plan.MONTHLY), 75050, date(2026, 11, 30)
    ),
)
REPORT = MonthReport(NOV, ROWS)


def test_file_names_follow_the_month() -> None:
    assert file_name(NOV, "xlsx") == "report-2026-11.xlsx"
    assert file_name(Month(2027, 1), "pdf") == "report-2027-01.pdf"


def test_the_title_names_the_month_in_hebrew() -> None:
    assert title(NOV) == "דוח חודשי: נובמבר 2026"
    assert title(Month(2027, 1)) == "דוח חודשי: ינואר 2027"


def test_two_plans_are_joined_in_order() -> None:
    assert plan_names(ROWS[2]) == "כרטיסייה + חודשי"
    assert plan_names(ROWS[0]) == "חודשי"


# --- Excel ---------------------------------------------------------------


def sheet_of(data: bytes):  # openpyxl's worksheet type is loose
    return load_workbook(io.BytesIO(data)).active


def test_the_workbook_is_right_to_left_with_title_and_headings() -> None:
    sheet = sheet_of(excel(REPORT))

    assert sheet.sheet_view.rightToLeft is True
    assert sheet.title == "2026-11"
    assert sheet["A1"].value == title(NOV)
    assert tuple(cell.value for cell in sheet[3]) == HEADINGS


def test_each_row_has_exact_amounts_and_real_dates() -> None:
    sheet = sheet_of(excel(REPORT))

    rows = [tuple(cell.value for cell in sheet[n]) for n in (4, 5, 6)]
    assert rows == [
        ("דנה", "לוי", "חודשי", 250, datetime(2026, 11, 30)),
        ("יוסי", "כהן", "כניסה בודדת", 120, None),
        ("מאיה", "כץ", "כרטיסייה + חודשי", 750.5, datetime(2026, 11, 30)),
    ]
    assert sheet["D4"].number_format == "#,##0.00"
    assert sheet["E4"].number_format == "dd/mm/yyyy"


def test_the_last_row_is_the_total() -> None:
    sheet = sheet_of(excel(REPORT))

    assert sheet.max_row == 7
    assert sheet["A7"].value == TOTAL
    assert Decimal(str(sheet["D7"].value)) == Decimal("1120.50")


def test_an_empty_month_has_headings_and_a_zero_total() -> None:
    sheet = sheet_of(excel(MonthReport(NOV, ())))

    assert sheet.max_row == 4
    assert sheet["A4"].value == TOTAL
    assert sheet["D4"].value == 0


# --- PDF -----------------------------------------------------------------


def pages(data: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", data))


def test_the_pdf_renders_on_one_page() -> None:
    data = pdf(REPORT)

    assert data.startswith(b"%PDF")
    assert pages(data) == 1


def test_a_long_report_runs_onto_more_pages() -> None:
    rows = tuple(
        ReportRow(n, "דנה", f"לוי {n}", (Plan.MONTHLY,), 25000, date(2026, 11, 30))
        for n in range(80)
    )

    assert pages(pdf(MonthReport(NOV, rows))) > 1


def test_an_empty_month_still_makes_a_pdf() -> None:
    assert pdf(MonthReport(NOV, ())).startswith(b"%PDF")
