"""The ``activity_log`` table: one row for every change a staff member makes
(design doc: "Activity log" and "Data model").

Each row is an event in the past, not a version of anything: the current
state lives in the changed table itself, and nothing reads this one to
work it out. Rows are added, never changed or deleted. Two triggers in the
migration refuse UPDATE and DELETE in the database itself, since the log is
kept as evidence (for the insurer, among others). Writing a row goes
through ``app.core.activity_log``.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.models.base import Base


class ActivityLogEntry(Base):
    __tablename__ = "activity_log"
    __table_args__ = (
        # SQLite keeps JSON as plain text; this keeps it parseable, so the
        # log screen can always show an entry.
        CheckConstraint(
            "before_json IS NULL OR json_valid(before_json)",
            name="before_json_is_json",
        ),
        CheckConstraint(
            "after_json IS NULL OR json_valid(after_json)",
            name="after_json_is_json",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Who made the change. Never empty: at first-run setup the new manager
    # is recorded as making it. No cascade: staff are deactivated, never
    # deleted.
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"), index=True)
    # "<area>.<verb>", e.g. "staff.change_role". Which actions exist is
    # defined in code (``activity_log.Action``), with no CHECK here, so a new
    # action needs no migration.
    action: Mapped[str] = mapped_column(Text)
    # What was changed, e.g. "staff_user" and its id. The id is empty for
    # things without one, such as the gym settings.
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    # The changed values before and after, as JSON. Empty when there is no
    # "before" (a creation) or the values are secret (a PIN reset).
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(default=utc_now, index=True)


# Everything that happened to one thing, e.g. a customer's history.
Index(
    "ix_activity_log_target",
    ActivityLogEntry.target_type,
    ActivityLogEntry.target_id,
)
