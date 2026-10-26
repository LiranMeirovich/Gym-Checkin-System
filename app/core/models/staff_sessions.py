"""The ``staff_sessions`` table: one row per staff login on the admin app
(design doc: "Staff login and lock screen").

The browser holds a random token in the ``gym_staff`` cookie; only its
SHA-256 hash is stored here, so a copy of the database can't be used to
log in. Rows are ended, never deleted, so they double as a login history.
The timeouts live in ``app.core.staff_sessions``.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.staff import StaffUser


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    __table_args__ = (
        # A SHA-256 hex digest and nothing else, so a plain token can't be
        # stored by mistake.
        CheckConstraint(
            "length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'",
            name="token_hash_is_sha256_hex",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: staff are deactivated, never deleted.
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    # The last request that counted as activity; the idle timeout runs
    # from here.
    last_seen_at: Mapped[datetime] = mapped_column(default=utc_now)
    # Set by Lock, or by the next login on the same browser. A session
    # that timed out keeps ended_at empty: it's refused by its timestamps.
    ended_at: Mapped[datetime | None]

    staff: Mapped[StaffUser] = relationship()
