"""Doctor's notes: staff add one to a health form with a "yes" answer, and
the form then counts (design doc: "Health form"; decisions 0004, 0031).
Or the manager accepts the form without one (``accept_form()``, decision
0041). Until one of the two, the form still lets the customer in, and it
waits on the manager's "forms to review" list.

Adding a note has two parts, so the slow one stays outside the request's
write lock (decision 0027):

1. ``check_note_image()`` checks the uploaded image and makes a clean copy.
   It touches no database, so the route calls it first.
2. ``add_doctor_note()`` adds it to the customer's form that counts today,
   which must be waiting for a note. Logged, with the staff member.

The clean copy is always a JPEG: the photo's orientation is applied, then
it is shrunk to ``NOTE_MAX_SIDE`` and re-encoded, so nothing but the pixels
is stored (a phone photo's EXIF data can hold where it was taken).

Viewing a note is the manager's, like the form's own contents, and every
opening is logged (``open_doctor_note()``).

Every function that takes ``db`` works inside the caller's transaction and
never commits.
"""

import io
from dataclasses import dataclass
from datetime import date

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
from app.core.customers import CustomerInactiveError
from app.core.health_forms import FormState, counting_form, status_of
from app.core.models import (
    Customer,
    DoctorNote,
    HealthForm,
    HealthFormAcceptance,
    ImageType,
    StaffUser,
)
from app.core.models.doctor_notes import IMAGE_MAX_BYTES

# What the browser may send. It shrinks photos first, so this only keeps a
# runaway upload out.
UPLOAD_MAX_BYTES = 12 * 1024 * 1024
# Readable for a doctor's note on screen, and far under IMAGE_MAX_BYTES.
NOTE_MAX_SIDE = 2500
# Refuse an image claiming more pixels than this before decoding it (a
# small file can claim a huge image).
_MAX_PIXELS = 50_000_000
_MIN_SIDE = 200
_JPEG_QUALITY = 85


class InvalidNoteImageError(ValueError):
    """Not a usable note: not a JPEG or PNG, too large, or too small."""


class NoNoteNeededError(ValueError):
    """The customer's form that counts today isn't waiting for review (a
    doctor's note or the manager's acceptance): it's already valid, or
    there is none (missing or expired)."""

    def __init__(self, state: FormState) -> None:
        super().__init__(f"health form is {state.value}")
        self.state = state


@dataclass(frozen=True)
class CheckedImage:
    """A clean copy of an uploaded note, ready to store."""

    data: bytes
    content_type: ImageType


def check_note_image(upload: bytes) -> CheckedImage:
    """Check an uploaded note (a JPEG or PNG photo or scan) and return a
    clean JPEG copy: upright, at most ``NOTE_MAX_SIDE`` on its longer
    side, without metadata."""
    if not upload or len(upload) > UPLOAD_MAX_BYTES:
        raise InvalidNoteImageError("size")
    try:
        with Image.open(io.BytesIO(upload), formats=["JPEG", "PNG"]) as image:
            width, height = image.size
            if width * height > _MAX_PIXELS:
                raise InvalidNoteImageError("too many pixels")
            if min(width, height) < _MIN_SIDE:
                raise InvalidNoteImageError("too small")
            upright = ImageOps.exif_transpose(image)
            upright.thumbnail((NOTE_MAX_SIDE, NOTE_MAX_SIDE))
            pixels = _on_white(upright)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidNoteImageError("not an image") from error

    out = io.BytesIO()
    pixels.save(out, format="JPEG", quality=_JPEG_QUALITY)
    data = out.getvalue()
    if len(data) > IMAGE_MAX_BYTES:
        raise InvalidNoteImageError("too large after shrinking")
    return CheckedImage(data, ImageType.JPEG)


def _on_white(image: Image.Image) -> Image.Image:
    """``image`` as RGB, with any transparency printed on white."""
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        sheet = Image.new("RGBA", rgba.size, "white")
        sheet.alpha_composite(rgba)
        return sheet.convert("RGB")
    return image.convert("RGB")


def add_doctor_note(
    db: Session,
    customer: Customer,
    image: CheckedImage,
    *,
    by: StaffUser,
    today: date,
) -> DoctorNote:
    """Staff member ``by`` adds ``image`` as the doctor's note for
    ``customer``'s form that counts on ``today`` (an Israel-local date),
    which must be waiting for one.

    Raises ``CustomerInactiveError`` or ``NoNoteNeededError``.
    """
    form = _waiting_form(db, customer, today)
    note = DoctorNote(
        health_form_id=form.id,
        image=image.data,
        content_type=image.content_type,
        staff_user_id=by.id,
    )
    db.add(note)
    db.flush()
    record(
        db,
        by,
        Action.HEALTH_FORM_ADD_DOCTOR_NOTE,
        Target.HEALTH_FORM,
        form.id,
        after={"doctor_note_id": note.id},
    )
    return note


def accept_form(
    db: Session, customer: Customer, *, by: StaffUser, today: date
) -> HealthFormAcceptance:
    """Manager ``by`` accepts ``customer``'s form that counts on ``today``
    (an Israel-local date) without a doctor's note; it must be waiting for
    review. The form then counts like one with a note (decision 0041). The
    caller checks ``health_forms.accept``.

    Raises ``CustomerInactiveError`` or ``NoNoteNeededError``.
    """
    form = _waiting_form(db, customer, today)
    acceptance = HealthFormAcceptance(health_form_id=form.id, staff_user_id=by.id)
    db.add(acceptance)
    db.flush()
    record(db, by, Action.HEALTH_FORM_ACCEPT, Target.HEALTH_FORM, form.id)
    return acceptance


def _waiting_form(db: Session, customer: Customer, today: date) -> HealthForm:
    """``customer``'s form that counts on ``today``, which must be waiting
    for review. Raises ``CustomerInactiveError`` or ``NoNoteNeededError``."""
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    form = counting_form(db, customer, today)
    state = status_of(db, form).state
    if form is None or state is not FormState.NEEDS_DOCTOR_NOTE:
        raise NoNoteNeededError(state)
    return form


def accepted_forms(db: Session, forms: list[HealthForm]) -> set[int]:
    """The ids of those of ``forms`` the manager accepted without a note."""
    return set(
        db.scalars(
            select(HealthFormAcceptance.health_form_id).where(
                HealthFormAcceptance.health_form_id.in_([form.id for form in forms])
            )
        )
    )


def notes_by_form(db: Session, forms: list[HealthForm]) -> dict[int, list[int]]:
    """The ids of each form's notes, oldest first, keyed by form id. The
    images stay unloaded."""
    found: dict[int, list[int]] = {form.id: [] for form in forms}
    rows = db.execute(
        select(DoctorNote.health_form_id, DoctorNote.id)
        .where(DoctorNote.health_form_id.in_(found))
        .order_by(DoctorNote.id)
    )
    for form_id, note_id in rows:
        found[form_id].append(note_id)
    return found


def note_of(db: Session, customer: Customer, note_id: int) -> DoctorNote | None:
    """One of the customer's notes, or None if ``note_id`` isn't theirs."""
    note = db.get(DoctorNote, note_id)
    if note is None or note.health_form.customer_id != customer.id:
        return None
    return note


def open_doctor_note(db: Session, note: DoctorNote, *, by: StaffUser) -> bytes:
    """A note's image, for the manager. Every opening is written to the
    activity log, like opening the form itself; the caller checks
    ``health_forms.view_contents``."""
    record(db, by, Action.DOCTOR_NOTE_OPEN, Target.DOCTOR_NOTE, note.id)
    return note.image
