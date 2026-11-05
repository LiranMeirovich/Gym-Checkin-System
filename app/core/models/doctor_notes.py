"""The ``doctor_notes`` table: a doctor's note added by staff to a health
form that had a "yes" answer (design doc: "Health form"; decisions 0004,
0031).

A form with any "yes" (``health_forms.needs_doctor_note``) counts only
once a note is added for that form. The note belongs to its form: a newer
form with a "yes" needs a note of its own. The image is a JPEG or PNG; the
database checks its opening bytes match ``content_type`` and caps its size.

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both). A note added by mistake is not removed: the right
one is added next to it, and the manager sees every note.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, LargeBinary
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.health_forms import HealthForm
from app.core.models.staff import StaffUser

# A phone photo shrunk by the browser is far smaller; the cap only keeps a
# runaway upload out.
IMAGE_MAX_BYTES = 5 * 1024 * 1024


class ImageType(StrEnum):
    """The image formats a note may be. The values are what the database
    stores, and what the browser is told when the manager opens one."""

    JPEG = "image/jpeg"
    PNG = "image/png"


class DoctorNote(Base):
    __tablename__ = "doctor_notes"
    __table_args__ = (
        # The image is what its type says: the format's opening bytes. "IS",
        # not "=": substr() of an empty blob is NULL, and a NULL CHECK
        # would pass.
        CheckConstraint(
            "typeof(image) = 'blob'"
            f" AND length(image) <= {IMAGE_MAX_BYTES}"
            " AND ((content_type = 'image/jpeg'"
            " AND substr(image, 1, 3) IS X'FFD8FF')"
            " OR (content_type = 'image/png'"
            " AND substr(image, 1, 8) IS X'89504E470D0A1A0A'))",
            name="image_matches_its_type",
        ),
        Index(None, "health_form_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: forms are never deleted.
    health_form_id: Mapped[int] = mapped_column(ForeignKey("health_forms.id"))
    # Deferred: status checks never load it.
    image: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    content_type: Mapped[ImageType] = mapped_column(
        Enum(
            ImageType,
            name="image_type",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda types: [t.value for t in types],
        )
    )
    # Who added it.
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    health_form: Mapped[HealthForm] = relationship()
    staff: Mapped[StaffUser] = relationship()
