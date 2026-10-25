"""The ``staff_users`` table: one row per manager or instructor (design doc:
"Data model"; decision 0018).

Rows are deactivated, never deleted: check-ins, health forms and the
activity log will point at them. The rules the database can't check (the
last active manager, PIN format, the lockout) live in ``app.core.staff``.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Enum, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.models.base import Base
from app.core.permissions import Role


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (
        CheckConstraint(
            "length(display_name) BETWEEN 1 AND 50", name="display_name_length"
        ),
        # Only a hash can be stored; a plain PIN can't slip in by mistake.
        # Changing the hashing algorithm means a migration for this check.
        CheckConstraint("pin_hash LIKE '$argon2id$%'", name="pin_hash_is_argon2id"),
        CheckConstraint("failed_attempts >= 0", name="failed_attempts_not_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Shown on the lock screen, where staff tap their name to log in.
    display_name: Mapped[str] = mapped_column(Text)
    # Stored as "manager" / "instructor", with a CHECK constraint.
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    pin_hash: Mapped[str] = mapped_column(Text)
    # Wrong PINs in a row; reset by a correct one.
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # The latest of those wrong PINs. A wrong PIN long after it starts the
    # count again, so typos weeks apart don't add up to a lockout.
    last_failed_at: Mapped[datetime | None]
    # Set after too many wrong PINs; no login until it passes.
    locked_until: Mapped[datetime | None]
    # Deactivate instead of deleting.
    active: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="active"), default=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


# Two active staff members can't share a name, ignoring case, since the
# lock screen tells them apart by name. A deactivated member's name can be
# reused. SQLite's lower() only folds ASCII; Hebrew has no case anyway.
Index(
    "uq_staff_users_active_display_name",
    func.lower(StaffUser.display_name),
    unique=True,
    sqlite_where=StaffUser.active,
)
