"""The current time, and turning stored times into local display time.

Timestamps are stored in UTC and shown in the configured timezone (Israel
time by default), so daylight-saving switches never shift a stored time.
Code gets "now" from ``utc_now()``, never ``datetime.now()`` (which is
naive local time) or ``datetime.utcnow()`` (naive, and deprecated).
"""

from datetime import UTC, datetime

from app.core.config import get_settings


def utc_now() -> datetime:
    """The current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def to_local(moment: datetime) -> datetime:
    """``moment`` in the configured display timezone.

    Refuses naive datetimes: without a timezone there's no way to know
    which instant it means, and guessing is how times end up an hour off.
    """
    if moment.tzinfo is None:
        raise ValueError("naive datetime: attach a timezone first")
    return moment.astimezone(get_settings().tz)
