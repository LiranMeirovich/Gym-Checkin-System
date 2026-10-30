"""The calendar month type and its column type."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select, text

from app.core import months
from app.core.models.base import MonthColumn
from app.core.months import Month


def test_text_form_round_trips() -> None:
    assert str(Month(2026, 3)) == "2026-03"
    assert Month.parse("2026-03") == Month(2026, 3)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "2026",
        "2026-3",
        "2026-13",
        "2026-00",
        "2026-03-01",
        " 2026-03",
        "2026-03\n",
        "0999-01",
        "٢٠٢٦-٠٣",
    ],
)
def test_parse_refuses_anything_else(bad: str) -> None:
    with pytest.raises(ValueError):
        Month.parse(bad)


@pytest.mark.parametrize(("year", "month"), [(2026, 0), (2026, 13), (999, 1)])
def test_an_impossible_month_cant_be_made(year: int, month: int) -> None:
    with pytest.raises(ValueError):
        Month(year, month)


def test_order_is_by_time_and_matches_the_text() -> None:
    in_order = [Month(2025, 12), Month(2026, 1), Month(2026, 2), Month(2026, 10)]
    assert sorted(reversed(in_order)) == in_order
    assert sorted(str(m) for m in reversed(in_order)) == [str(m) for m in in_order]


@pytest.mark.parametrize(
    ("start", "added", "expected"),
    [
        (Month(2026, 3), 0, Month(2026, 3)),
        (Month(2026, 3), 1, Month(2026, 4)),
        (Month(2026, 11), 2, Month(2027, 1)),
        (Month(2026, 12), 1, Month(2027, 1)),
        (Month(2026, 1), -1, Month(2025, 12)),
        (Month(2026, 3), 24, Month(2028, 3)),
    ],
)
def test_plus_crosses_years(start: Month, added: int, expected: Month) -> None:
    assert start.plus(added) == expected


def test_of_a_date() -> None:
    assert Month.of(date(2026, 10, 31)) == Month(2026, 10)


def test_current_is_the_gyms_month_not_utcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    # 22:30 UTC on 31 October is already 1 November in Israel (UTC+2).
    monkeypatch.setattr(
        months, "utc_now", lambda: datetime(2026, 10, 31, 22, 30, tzinfo=UTC)
    )
    assert Month.current() == Month(2026, 11)


def test_column_stores_the_text_and_reads_back_a_month() -> None:
    table = Table(
        "t",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("month", MonthColumn),
    )
    engine = create_engine("sqlite://")
    table.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"month": Month(2026, 3)}, {"month": None}])
        assert connection.scalars(text("SELECT month FROM t ORDER BY id")).all() == [
            "2026-03",
            None,
        ]
        assert connection.scalars(select(table.c.month).order_by(table.c.id)).all() == [
            Month(2026, 3),
            None,
        ]
