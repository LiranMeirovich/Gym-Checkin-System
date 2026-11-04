"""The ``health_forms`` table: one row per health declaration a customer
signs (design doc: "Health form"; decisions 0004, 0031).

Forms are filled in online only: on the customer's phone, or on a gym
device at the desk. Each row keeps the answers, the form version (the
wording lives in code under that version) and a PDF snapshot of exactly
what was signed, so the form stays readable after the questions change.

Rows are only ever added, never changed or deleted (triggers in the
migration refuse both); the newest valid form counts. ``expires_on`` is
stored on each row, so changing how long a form lasts never rewrites old
ones. The rules the database can't check (which answers make a form need
a doctor's note, how long it lasts, who signs) live in
``app.core.health_forms``.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.customers import Customer

# A one-page snapshot with a signature is far smaller; the cap only keeps
# a runaway document out.
DOCUMENT_MAX_BYTES = 5 * 1024 * 1024


def _is_a_date(column: str) -> str:
    # A real calendar date in YYYY-MM-DD, as on ``customers.date_of_birth``.
    return f"date({column}) IS {column}"


class HealthForm(Base):
    __tablename__ = "health_forms"
    __table_args__ = (
        CheckConstraint(_is_a_date("signed_on"), name="signed_on_is_a_date"),
        CheckConstraint(_is_a_date("expires_on"), name="expires_on_is_a_date"),
        CheckConstraint("expires_on > signed_on", name="expires_after_signed"),
        CheckConstraint("json_valid(answers_json)", name="answers_json_is_json"),
        CheckConstraint(
            "length(signer_name) BETWEEN 1 AND 100", name="signer_name_length"
        ),
        CheckConstraint("length(form_version) BETWEEN 1 AND 20", name="version_length"),
        # A PDF and nothing else: it starts with the PDF header. "IS", not
        # "=": substr() of an empty blob is NULL, and a NULL CHECK would pass.
        CheckConstraint(
            "typeof(document) = 'blob'"
            " AND substr(document, 1, 5) IS CAST('%PDF-' AS BLOB)"
            f" AND length(document) <= {DOCUMENT_MAX_BYTES}",
            name="document_is_a_pdf",
        ),
        # The customer's newest form first.
        Index(None, "customer_id", "signed_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: customers are deactivated, never deleted.
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    # Which wording was signed; the questions live in code under it.
    form_version: Mapped[str] = mapped_column(Text)
    # The answers, gender and free-text details, keyed by question.
    answers_json: Mapped[str] = mapped_column(Text)
    # Any "yes" answer: the form counts only once a doctor's note is added
    # (milestone 3, feature 4).
    needs_doctor_note: Mapped[bool] = mapped_column(Boolean)
    # The customer, or their parent or guardian for an under-18.
    signer_name: Mapped[str] = mapped_column(Text)
    signed_by_guardian: Mapped[bool] = mapped_column(Boolean)
    # Israel-local calendar dates. ``expires_on`` is the last valid day.
    signed_on: Mapped[date]
    expires_on: Mapped[date]
    # The PDF snapshot. Deferred: status checks never load it.
    document: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    customer: Mapped[Customer] = relationship()
