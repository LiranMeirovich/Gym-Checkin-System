"""The health form's PDF snapshot and the signature check. Names are made
up."""

import io
import re
from datetime import date

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from app.core.health_form_pdf import (
    InvalidSignatureError,
    SnapshotDetails,
    check_signature,
    render_snapshot,
)
from app.core.health_forms import (
    CURRENT_VERSION,
    DETAILS_MAX_LENGTH,
    FORMS,
    SIGNER_NAME_MAX_LENGTH,
    CheckedForm,
    check_form,
)


def signature(**info: str) -> bytes:
    image = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(20, 100), (100, 30), (180, 90)], "black", 5)
    text = PngImagePlugin.PngInfo()
    for key, value in info.items():
        text.add_text(key, value)
    out = io.BytesIO()
    image.save(out, "PNG", pnginfo=text)
    return out.getvalue()


def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def filled(*, longest: bool) -> CheckedForm:
    """A usual form (all "no", short names), or everything as long as it
    may be, with every answer "yes" and both details lines full."""
    form = FORMS[CURRENT_VERSION]
    return check_form(
        version=CURRENT_VERSION,
        answers={q.key: longest for q in form.questions},
        details={
            q.key: "ד" * DETAILS_MAX_LENGTH
            for q in form.questions
            if q.has_details and longest
        },
        gender="male",
        signer_name="א" * SIGNER_NAME_MAX_LENGTH if longest else "Dana Levi",
        confirmed=True,
        signature_png=signature(),
    )


def details(
    *, guardian: bool, gym_name: str | None = "חדר כושר לדוגמה"
) -> SnapshotDetails:
    return SnapshotDetails(
        gym_name=gym_name,
        customer_name="נועה לוי",
        date_of_birth=date(2010, 5, 1),
        phone="+972501234567",
        signed_on=date(2026, 11, 4),
        expires_on=date(2027, 11, 3),
        signed_by_guardian=guardian,
    )


@pytest.mark.parametrize("guardian", [False, True], ids=["adult", "guardian"])
def test_a_usual_form_fits_on_one_page(guardian: bool) -> None:
    checked = filled(longest=False)

    pdf = render_snapshot(checked, details(guardian=guardian), checked.signature_png)

    assert pdf.startswith(b"%PDF-")
    assert pages(pdf) == 1


@pytest.mark.parametrize("guardian", [False, True], ids=["adult", "guardian"])
def test_the_longest_form_fits_on_two_pages(guardian: bool) -> None:
    checked = filled(longest=True)

    pdf = render_snapshot(checked, details(guardian=guardian), checked.signature_png)

    assert pages(pdf) <= 2


def test_the_snapshot_renders_without_a_gym_name() -> None:
    checked = filled(longest=False)

    pdf = render_snapshot(
        checked, details(guardian=False, gym_name=None), checked.signature_png
    )

    assert pdf.startswith(b"%PDF-")


def test_the_signature_copy_drops_everything_but_the_pixels() -> None:
    clean = check_signature(signature(Comment="made-up metadata"))

    with Image.open(io.BytesIO(clean)) as image:
        assert image.format == "PNG"
        assert "Comment" not in image.info


def test_a_huge_signature_is_refused() -> None:
    with pytest.raises(InvalidSignatureError):
        check_signature(b"\x89PNG\r\n\x1a\n" + b"0" * 400_000)
