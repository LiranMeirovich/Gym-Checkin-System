"""Current time and local display time, including Israel's daylight-saving
switches."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import to_local, utc_now


@pytest.fixture(autouse=True)
def dev_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")


def test_utc_now_is_aware_utc() -> None:
    now = utc_now()

    assert now.tzinfo is UTC
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


@pytest.mark.parametrize(
    ("utc", "local"),
    [
        # Winter time is UTC+2.
        (datetime(2026, 1, 15, 7, 0, tzinfo=UTC), "2026-01-15 09:00 +0200"),
        # Summer time starts Friday 27 March 2026: 02:00 jumps to 03:00.
        (datetime(2026, 3, 26, 23, 59, tzinfo=UTC), "2026-03-27 01:59 +0200"),
        (datetime(2026, 3, 27, 0, 0, tzinfo=UTC), "2026-03-27 03:00 +0300"),
        # Summer time ends Sunday 25 October 2026: 02:00 falls back to 01:00,
        # so 01:00-01:59 local happens twice; UTC keeps the two apart.
        (datetime(2026, 10, 24, 22, 30, tzinfo=UTC), "2026-10-25 01:30 +0300"),
        (datetime(2026, 10, 24, 23, 30, tzinfo=UTC), "2026-10-25 01:30 +0200"),
    ],
)
def test_to_local_follows_israel_daylight_saving(utc: datetime, local: str) -> None:
    assert to_local(utc).strftime("%Y-%m-%d %H:%M %z") == local


def test_to_local_uses_the_configured_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_TIMEZONE", "Europe/London")

    local = to_local(datetime(2026, 1, 15, 7, 0, tzinfo=UTC))

    assert local.strftime("%H:%M %z") == "07:00 +0000"


def test_to_local_refuses_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_local(datetime(2026, 1, 15, 7, 0))
