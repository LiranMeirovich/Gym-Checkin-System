"""A month's report as an Excel file and a PDF (design doc: "Monthly
report", "Format and storage").

Both are made from a ``MonthReport`` and work nothing out themselves: the
amounts, end dates and plans come from ``app.core.reports``. Both are in
Hebrew, right to left, with the columns first name, last name, plan,
payment and subscription end, and a total row. Money stays whole agorot
until it's written: Excel gets an exact ``Decimal`` in shekels, the PDF
the same text as the screens (₪250, ₪19.90).

The PDF uses fpdf2 with uharfbuzz shaping and the bundled Heebo font, as
the health form's snapshot does. Letters Heebo lacks (Cyrillic, Arabic)
print blank.
"""

import io
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from fpdf.enums import Align, TableBordersLayout
from fpdf.fonts import FontFace
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from app.core.health_form_pdf import FONT
from app.core.models import Plan
from app.core.months import Month
from app.core.reports import MonthReport, ReportRow

# The same names as the screens' ``PLAN_NAMES`` (frontend/src/shared/plans.ts):
# change both together.
PLAN_NAMES = {
    Plan.MONTHLY: "חודשי",
    Plan.TRI_MONTHLY: "שלושה חודשים",
    Plan.SINGLE_ENTRY: "כניסה בודדת",
    Plan.PUNCH_CARD: "כרטיסייה",
}

_MONTH_NAMES = (
    "ינואר",
    "פברואר",
    "מרץ",
    "אפריל",
    "מאי",
    "יוני",
    "יולי",
    "אוגוסט",
    "ספטמבר",
    "אוקטובר",
    "נובמבר",
    "דצמבר",
)

HEADINGS = ("שם פרטי", "שם משפחה", "מנוי", "תשלום (₪)", "סיום מנוי")
TOTAL = 'סה"כ'

_FAMILY = "Heebo"


def file_name(month: Month, extension: str) -> str:
    """``report-2026-11.xlsx`` for ``extension`` ``xlsx``."""
    return f"report-{month}.{extension}"


def title(month: Month) -> str:
    """ "דוח חודשי: נובמבר 2026"."""
    return f"דוח חודשי: {_MONTH_NAMES[month.month - 1]} {month.year}"


def plan_names(row: ReportRow) -> str:
    """The row's plans in Hebrew, in order: "כרטיסייה + חודשי"."""
    return " + ".join(PLAN_NAMES[plan] for plan in row.plans)


# --- Excel ---------------------------------------------------------------


def excel(report: MonthReport) -> bytes:
    """The report as an .xlsx workbook: one right-to-left sheet with the
    title, the headings, a row per customer and the total."""
    book = Workbook()
    sheet = book.active
    if sheet is None:  # a new workbook always has one sheet
        raise RuntimeError("openpyxl made a workbook without a sheet")
    sheet.title = str(report.month)
    sheet.sheet_view.rightToLeft = True
    bold = Font(bold=True)

    sheet.append([title(report.month)])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([])
    sheet.append(list(HEADINGS))
    for cell in sheet[3]:
        cell.font = bold
    for row in report.rows:
        sheet.append(
            [
                row.first_name,
                row.last_name,
                plan_names(row),
                _shekels(row.payment_agorot),
                row.ends_on,
            ]
        )
    sheet.append([TOTAL, None, None, _shekels(report.total_agorot), None])
    total_row = sheet.max_row
    for cell in sheet[total_row]:
        cell.font = bold

    for (payment,) in sheet.iter_rows(min_row=4, min_col=4, max_col=4):
        payment.number_format = "#,##0.00"
    for (ends,) in sheet.iter_rows(min_row=4, max_row=total_row - 1, min_col=5):
        ends.number_format = "dd/mm/yyyy"
        ends.alignment = Alignment(horizontal="right")
    for column, width in zip("ABCDE", (16, 18, 26, 14, 14), strict=True):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A4"

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _shekels(agorot: int) -> Decimal:
    # Exact: 1990 agorot is Decimal("19.90"), never a float.
    return Decimal(agorot).scaleb(-2)


# --- PDF -----------------------------------------------------------------


def pdf(report: MonthReport) -> bytes:
    """The report as an A4 PDF: the title, then a table with the headings
    repeated on every page and the total at the end."""
    doc = FPDF(format="A4")
    doc.set_margins(15, 12, 15)
    doc.set_auto_page_break(auto=True, margin=15)
    doc.add_font(
        _FAMILY, fname=FONT, variations={"": {"wght": 400}, "B": {"wght": 700}}
    )
    doc.set_text_shaping(use_shaping_engine=True, direction="rtl")
    doc.set_title(title(report.month))
    doc.add_page()

    doc.set_font(_FAMILY, "B", 16)
    doc.cell(0, 10, title(report.month), align=Align.R, new_x="LMARGIN", new_y="NEXT")
    doc.ln(3)

    doc.set_font(_FAMILY, "", 10)
    # fpdf2 lays a table out left to right: the columns go in reverse, so
    # the first name ends up on the right.
    widths = (28, 26, 50, 38, 38)
    with doc.table(
        col_widths=tuple(reversed(widths)),
        text_align=Align.R,
        line_height=7,
        borders_layout=TableBordersLayout.HORIZONTAL_LINES,
        headings_style=FontFace(emphasis="BOLD"),
        repeat_headings=1,
    ) as table:
        table.row(tuple(reversed(HEADINGS)))
        for row in report.rows:
            cells = (
                row.first_name,
                row.last_name,
                plan_names(row),
                _ltr(_money(row.payment_agorot)),
                "" if row.ends_on is None else _day(row.ends_on),
            )
            table.row(tuple(reversed(cells)))
        total = ("", _ltr(_money(report.total_agorot)), "", "", TOTAL)
        table.row(total, style=FontFace(emphasis="BOLD"))
    return bytes(doc.output())


def _money(agorot: int) -> str:
    # The screens' format (``formatShekels`` in ``shared/plans.ts``).
    shekels, rest = divmod(agorot, 100)
    return f"₪{shekels}" if rest == 0 else f"₪{shekels}.{rest:02d}"


def _day(day: date) -> str:
    return _ltr(f"{day:%d/%m/%Y}")


def _ltr(text: str) -> str:
    # Left-to-right isolate (LRI ... PDI), so the bidi algorithm keeps
    # 31/12/2026 and ₪1,250 in order inside a right-to-left cell.
    return f"⁦{text}⁩"
