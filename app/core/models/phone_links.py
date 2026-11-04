"""The ``link_codes`` and ``device_sessions`` tables: linking a customer's
phone (design doc: "Check-in flow", "Data model").

A staff member issues a 6-digit link code; the customer types their phone
number and the code on their phone, which then gets a device session. The
phone keeps a random token in the ``gym_device`` cookie. Both the code and
the token are stored only as SHA-256 hashes, so a copy of the database
holds neither.

Rows are never deleted. A code is marked used once; a device session is
revoked (Unlink, or replaced by a newer phone), so the rows double as a
history of linked phones. The rules the database can't check (expiry, the
newest code only, at most 3 phones) live in ``app.core.phone_links``.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.models.customers import Customer
from app.core.models.staff import StaffUser

USER_AGENT_MAX_LENGTH = 200


def _is_sha256_hex(column: str) -> str:
    # A SHA-256 hex digest and nothing else, so a plain code or token can't
    # be stored by mistake (as on ``staff_sessions.token_hash``).
    return f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'"


class LinkCode(Base):
    __tablename__ = "link_codes"
    __table_args__ = (
        CheckConstraint(_is_sha256_hex("code_hash"), name="code_hash_is_sha256_hex"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No cascade: customers are deactivated, never deleted.
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    code_hash: Mapped[str] = mapped_column(Text)
    # The staff member who issued it.
    created_by: Mapped[int] = mapped_column(ForeignKey("staff_users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    expires_at: Mapped[datetime]
    # Set once, when a phone links with it.
    used_at: Mapped[datetime | None]

    customer: Mapped[Customer] = relationship()
    staff: Mapped[StaffUser] = relationship()


class DeviceSession(Base):
    __tablename__ = "device_sessions"
    __table_args__ = (
        CheckConstraint(_is_sha256_hex("token_hash"), name="token_hash_is_sha256_hex"),
        CheckConstraint(
            f"length(user_agent) <= {USER_AGENT_MAX_LENGTH}", name="user_agent_length"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    # As the phone sent it, cut to USER_AGENT_MAX_LENGTH; empty if none.
    # Only for staff to tell the customer's phones apart.
    user_agent: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    # Refreshed on every check-in.
    last_seen_at: Mapped[datetime] = mapped_column(default=utc_now)
    # Set by Unlink, by a newer phone taking the place of the least
    # recently used one, or by the same browser linking again.
    revoked_at: Mapped[datetime | None]

    customer: Mapped[Customer] = relationship()
