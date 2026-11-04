"""The PDF snapshot of a signed health form, and checking the signature
image it carries (design doc: "Health form"; decision 0031).

The snapshot is exactly what was signed: the form's wording at its
version, the customer's details, every answer, the signer's name, the
dates and the signature. It's stored in the database with the form, so
it stays readable after the questions change.

Hebrew is right to left: fpdf2 shapes the text with HarfBuzz
(``uharfbuzz``) and the Heebo font, which also has Latin letters and
digits for names, dates and phone numbers.
"""

import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos
from PIL import Image, UnidentifiedImageError

from app.core.customers import display_phone

if TYPE_CHECKING:
    from app.core.health_forms import CheckedForm

FONT = Path(__file__).parent / "fonts" / "Heebo-Variable.ttf"
_FAMILY = "Heebo"

# The phone's canvas sends a PNG of a few kB to a few tens of kB.
SIGNATURE_MAX_BYTES = 300 * 1024
_SIGNATURE_MAX_SIDE = 3000
_SIGNATURE_MIN_SIDE = 50

_GENDER = {"male": "זכר", "female": "נקבה"}


class InvalidSignatureError(ValueError):
    """Not a usable signature: not a PNG, too large or small, or blank."""


def check_signature(png: bytes) -> bytes:
    """Check the signature image from the phone and return a clean copy:
    a PNG within the size limits with something drawn on it. The copy is
    re-encoded, so nothing but the pixels reaches the PDF."""
    if not png or len(png) > SIGNATURE_MAX_BYTES:
        raise InvalidSignatureError("size")
    try:
        with Image.open(io.BytesIO(png), formats=["PNG"]) as image:
            width, height = image.size
            if not (
                _SIGNATURE_MIN_SIDE <= width <= _SIGNATURE_MAX_SIDE
                and _SIGNATURE_MIN_SIDE <= height <= _SIGNATURE_MAX_SIDE
            ):
                raise InvalidSignatureError("dimensions")
            pixels = image.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidSignatureError("not a png") from error

    # Drawn on a white sheet, so a transparent background prints white.
    sheet = Image.new("RGBA", pixels.size, "white")
    sheet.alpha_composite(pixels)
    flat = sheet.convert("L")
    # Blank: every pixel (nearly) white.
    if flat.point(lambda value: 255 if value < 200 else 0).getbbox() is None:
        raise InvalidSignatureError("blank")
    out = io.BytesIO()
    flat.save(out, format="PNG")
    return out.getvalue()


@dataclass(frozen=True)
class SnapshotDetails:
    """What the snapshot shows besides the form itself."""

    # None before first-run setup.
    gym_name: str | None
    customer_name: str
    date_of_birth: date
    phone: str
    signed_on: date
    expires_on: date
    signed_by_guardian: bool


def render_snapshot(
    checked: "CheckedForm", details: SnapshotDetails, signature_png: bytes
) -> bytes:
    """The signed form as a PDF. ``signature_png`` is the output of
    ``check_signature()``."""
    form = checked.form
    pdf = _Pdf()
    pdf.set_title(form.title)
    pdf.add_page()

    pdf.heading(form.title, size=16)
    if details.gym_name:
        pdf.line_of(details.gym_name, size=11)
    pdf.ln(3)

    pdf.line_of(
        f"שם פרטי ושם משפחה: {details.customer_name}"
        f"    תאריך לידה: {_day(details.date_of_birth)}"
    )
    pdf.line_of(
        f"מין: {_GENDER[checked.gender.value]}"
        f"    מספר טלפון: {_ltr(display_phone(details.phone))}"
    )
    pdf.line_of(form.wording_note, size=9)
    pdf.ln(2)

    pdf.heading(form.part_a_title)
    for note in form.notes(details.gym_name):
        pdf.paragraph(note, size=10)
    pdf.ln(1)
    pdf.line_of(form.questions_intro, bold=True)
    for number, question in enumerate(form.questions, start=1):
        answer = "כן" if checked.answers[question.key] else "לא"
        pdf.question_row(f"{number}. {question.text}", answer)
        if question.has_details:
            pdf.line_of(f"פירוט: {checked.details.get(question.key, '')}", size=10)
    pdf.ln(2)

    pdf.heading(form.part_b_title)
    for paragraph in form.declaration:
        pdf.paragraph(paragraph, size=10)
    pdf.line_of(f"תוקף ההצהרה עד: {_day(details.expires_on)}", bold=True)
    pdf.ln(2)

    if details.signed_by_guardian:
        pdf.line_of(form.guardian_title, bold=True)
        pdf.paragraph(form.consent(details.customer_name))
        name_label, signature_label = "שם ההורה", "חתימת הורה"
    else:
        name_label, signature_label = "שם ושם משפחה", "חתימה"
    pdf.line_of(
        f"{name_label}: {checked.signer_name}    תאריך: {_day(details.signed_on)}"
    )
    pdf.signature(f"{signature_label}:", signature_png)

    pdf.ln(4)
    pdf.line_of(f"גרסת טופס: {form.version}", size=8)
    return bytes(pdf.output())


def _ltr(text: str) -> str:
    # Wrapped as left-to-right (LRI ... PDI), so the bidi algorithm keeps
    # 04/11/2026 and 050-1234567 in order inside a Hebrew line.
    return f"⁦{text}⁩"


def _day(day: date) -> str:
    return _ltr(f"{day:%d/%m/%Y}")


class _Pdf(FPDF):
    """A4 page with the Hebrew font, right to left. Every write spans the
    full width, aligned right."""

    def __init__(self) -> None:
        super().__init__(format="A4")
        self.set_margins(18, 12, 18)
        self.set_auto_page_break(auto=True, margin=15)
        # One variable font file, registered as regular and bold.
        self.add_font(
            _FAMILY, fname=FONT, variations={"": {"wght": 400}, "B": {"wght": 700}}
        )
        self.set_text_shaping(use_shaping_engine=True, direction="rtl")
        self.set_font(_FAMILY, size=11)

    def _text(self, text: str, *, size: float, bold: bool, align: Align) -> None:
        self.set_font(_FAMILY, "B" if bold else "", size)
        self.multi_cell(
            0,
            size * 0.5,
            text,
            align=align,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def heading(self, text: str, *, size: float = 13) -> None:
        self._text(text, size=size, bold=True, align=Align.R)
        self.ln(1)

    def line_of(self, text: str, *, size: float = 11, bold: bool = False) -> None:
        self._text(text, size=size, bold=bold, align=Align.R)

    def paragraph(self, text: str, *, size: float = 11) -> None:
        self._text(text, size=size, bold=False, align=Align.J)
        self.ln(1)

    def question_row(self, question: str, answer: str) -> None:
        # The question on the right, the answer in a column on the left.
        self.set_font(_FAMILY, "", 11)
        answer_width = 20
        height = 5.6
        self.cell(
            self.epw - answer_width, height, question, align=Align.R, new_x=XPos.LEFT
        )
        self.set_x(self.l_margin)
        self.set_font(_FAMILY, "B", 11)
        self.cell(
            answer_width,
            height,
            answer,
            border=1,
            align=Align.C,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def signature(self, label: str, png: bytes) -> None:
        # The label on the right, the signature in a box beside it; never
        # split across pages.
        label_width, width, height = 28, 60, 24
        if self.will_page_break(height):
            self.add_page()
        y = self.get_y()
        self.set_font(_FAMILY, "", 11)
        self.set_x(self.w - self.r_margin - label_width)
        self.cell(label_width, 7, label, align=Align.R)
        x = self.w - self.r_margin - label_width - width
        self.image(io.BytesIO(png), x=x, y=y, w=width, h=height, keep_aspect_ratio=True)
        self.rect(x, y, width, height)
        self.set_xy(self.l_margin, y + height)
