"""The ``customers`` table: one row per gym member (design doc: "Data
model"; decision 0023).

A phone number is one person, always: it's unique across every customer,
active or not, and stored in one form (E.164, ``+972501234567``) so every
way of typing it finds the same row. Customers are deactivated, never
deleted (decision 0021). The rules the database can't check (how a phone
is normalised, sensible birth dates, trimming names) live in
``app.core.customers``.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.models.base import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "length(first_name) BETWEEN 1 AND 50", name="first_name_length"
        ),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="last_name_length"),
        # Only the normalised form: "+972", a non-zero digit, then 8 digits
        # for a mobile (13 characters) or 7 for a landline (12).
        CheckConstraint(
            "phone GLOB '+972[1-9]*'"
            " AND substr(phone, 2) NOT GLOB '*[^0-9]*'"
            " AND length(phone) BETWEEN 12 AND 13",
            name="phone_is_e164_israeli",
        ),
        # A real calendar date in YYYY-MM-DD. "IS", not "=": date() of
        # anything else is NULL, and a NULL CHECK would pass.
        CheckConstraint(
            "date(date_of_birth) IS date_of_birth", name="date_of_birth_is_a_date"
        ),
        CheckConstraint("length(notes) <= 256", name="notes_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text, unique=True)
    # Sets the under-18 price. Required from the start; only the manager
    # changes it afterwards.
    date_of_birth: Mapped[date]
    # Empty when there are none, never NULL, so there's one way to say it.
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    # Deactivating only hides a customer from the default list. When it
    # happened is in the activity log.
    active: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="active"), default=True
    )
