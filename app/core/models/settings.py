"""The ``settings`` table: values the manager edits in the admin app (gym
name, emails, lock-screen minutes), as opposed to the deployment config in
``.env`` (decision 0014).

One row per key. Which keys exist, their types, defaults and validation
live in code, not here; a key with no row uses its default. Values are
stored as JSON text so lists and numbers read back with their type.
"""

from datetime import datetime

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.models.base import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    # JSON-encoded, e.g. '"Example Gym"', '5', '["a@example.com"]'.
    value: Mapped[str] = mapped_column(Text)
    # When the value last changed. Who changed it, and from what, goes in
    # the activity log, not here.
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
