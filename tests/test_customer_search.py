"""The customer list: name and phone search, the "came in" filter, sorting
and paging. Names and phone numbers are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core import customer_search
from app.core.customer_search import CameIn, SortBy, search_customers
from app.core.db import get_engine
from app.core.models import CheckIn, CheckInMethod, Customer, StaffUser
from app.core.permissions import Role

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
# 14:00 in Israel (UTC+2 in November).
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
# Midnight in Israel, 3 November: the start of "the last 7 days".
WEEK_START = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)
# Midnight in Israel, 11 October (still summer time, UTC+3): the start of
# "the last 30 days".
MONTH_START = datetime(2026, 10, 10, 21, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(customer_search, "utc_now", lambda: NOW)


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def staff(db: Session) -> StaffUser:
    member = StaffUser(
        display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH
    )
    db.add(member)
    db.flush()
    return member


def add(
    db: Session, first: str, last: str, phone: str, *, active: bool = True
) -> Customer:
    customer = Customer(
        first_name=first,
        last_name=last,
        phone=phone,
        date_of_birth=date(1990, 1, 1),
        active=active,
    )
    db.add(customer)
    db.flush()
    return customer


def check_in(db: Session, customer: Customer, staff: StaffUser, at: datetime) -> None:
    db.add(
        CheckIn(
            customer_id=customer.id,
            checked_in_at=at,
            method=CheckInMethod.MANUAL,
            staff_user_id=staff.id,
        )
    )
    db.flush()


def found(db: Session, **filters) -> list[Customer]:
    return [row.customer for row in search_customers(db, **filters).rows]


# --- Name search ---------------------------------------------------------


def test_no_text_lists_active_customers_by_name(db: Session) -> None:
    yael = add(db, "יעל", "אברהם", "+972501111111")
    dana_l = add(db, "דנה", "לוי", "+972502222222")
    dana_c = add(db, "דנה", "כהן", "+972503333333")
    gone = add(db, "אבי", "פרץ", "+972504444444", active=False)

    assert found(db) == [dana_c, dana_l, yael]
    assert found(db, active=False) == [gone]


def test_every_word_must_match_the_first_or_last_name(db: Session) -> None:
    dana_c = add(db, "דנה", "כהן", "+972501111111")
    dana_l = add(db, "דנה", "לוי", "+972502222222")
    add(db, "יעל", "כהן", "+972503333333")

    assert found(db, text="דנה") == [dana_c, dana_l]
    assert found(db, text="דנה כה") == [dana_c]
    assert found(db, text="  כהן   דנה ") == [dana_c]
    assert found(db, text="דנה מזרחי") == []


def test_a_name_matches_inside_a_word(db: Session) -> None:
    noa = add(db, "נועה", "בן-דוד", "+972501111111")

    assert found(db, text="דוד") == [noa]
    assert found(db, text="ועה") == [noa]


def test_latin_names_match_in_either_case(db: Session) -> None:
    noa = add(db, "Noa", "Levi", "+972501111111")

    assert found(db, text="noa LEVI") == [noa]


def test_wildcards_are_plain_characters(db: Session) -> None:
    add(db, "Noa", "Levi", "+972501111111")
    odd = add(db, "A_b", "100%", "+972502222222")

    assert found(db, text="%") == [odd]
    assert found(db, text="_") == [odd]
    assert found(db, text="\\") == []


def test_direction_marks_in_pasted_text_are_ignored(db: Session) -> None:
    dana = add(db, "דנה", "כהן", "+972501111111")

    assert found(db, text="‏דנה‎") == [dana]


def test_the_search_only_looks_at_the_chosen_list(db: Session) -> None:
    add(db, "דנה", "כהן", "+972501111111")
    gone = add(db, "דנה", "לוי", "+972502222222", active=False)

    assert found(db, text="דנה", active=False) == [gone]


# --- Phone search --------------------------------------------------------


def test_digits_search_the_number_as_written_in_israel(db: Session) -> None:
    noa = add(db, "Noa", "Levi", "+972501234567")
    dan = add(db, "Dan", "Golan", "+97231234567")

    assert found(db, text="4567") == [dan, noa]
    assert found(db, text="050-123") == [noa]
    assert found(db, text="050 123 4567") == [noa]
    assert found(db, text="03") == [dan]
    # The stored "+972" isn't part of the written number, and "972" on its
    # own is digits from inside one, not a country code.
    assert found(db, text="972") == []
    assert found(db, text="9725") == []


@pytest.mark.parametrize(
    "typed", ["+972 50 123 4567", "972501234567", "00972-50-1234567", "+972 050…"]
)
def test_a_number_with_the_country_code_is_its_local_form(
    db: Session, typed: str
) -> None:
    noa = add(db, "Noa", "Levi", "+972501234567")
    add(db, "Dan", "Golan", "+972521234567")

    assert found(db, text=typed.replace("…", "1234567")) == [noa]


def test_full_width_digits_are_read_as_digits(db: Session) -> None:
    noa = add(db, "Noa", "Levi", "+972501234567")

    assert found(db, text="４５６７") == [noa]


def test_digits_mixed_with_letters_are_a_name_search(db: Session) -> None:
    add(db, "Noa", "Levi", "+972501234567")

    assert found(db, text="Noa 4567") == []


# --- Came in -------------------------------------------------------------


def test_came_in_counts_israel_days(db: Session, staff: StaffUser) -> None:
    today = add(db, "A", "Today", "+972501111111")
    week_edge = add(db, "B", "WeekEdge", "+972502222222")
    before_week = add(db, "C", "BeforeWeek", "+972503333333")
    month_edge = add(db, "D", "MonthEdge", "+972504444444")
    long_ago = add(db, "E", "LongAgo", "+972505555555")
    never = add(db, "F", "Never", "+972506666666")
    check_in(db, today, staff, NOW - timedelta(hours=1))
    check_in(db, week_edge, staff, WEEK_START)
    check_in(db, before_week, staff, WEEK_START - timedelta(seconds=1))
    check_in(db, month_edge, staff, MONTH_START)
    check_in(db, long_ago, staff, MONTH_START - timedelta(seconds=1))

    assert found(db, came_in=CameIn.LAST_7_DAYS) == [today, week_edge]
    assert found(db, came_in=CameIn.LAST_30_DAYS) == [
        today,
        week_edge,
        before_week,
        month_edge,
    ]
    assert found(db, came_in=CameIn.NOT_IN_30_DAYS) == [long_ago, never]
    assert len(found(db, came_in=CameIn.ANY)) == 6


def test_the_latest_check_in_decides(db: Session, staff: StaffUser) -> None:
    back = add(db, "Noa", "Levi", "+972501111111")
    check_in(db, back, staff, MONTH_START - timedelta(days=90))
    check_in(db, back, staff, NOW - timedelta(days=1))

    assert found(db, came_in=CameIn.LAST_7_DAYS) == [back]
    assert found(db, came_in=CameIn.NOT_IN_30_DAYS) == []


def test_the_row_carries_the_latest_check_in(db: Session, staff: StaffUser) -> None:
    noa = add(db, "Noa", "Levi", "+972501111111")
    add(db, "Dan", "Golan", "+972502222222")
    check_in(db, noa, staff, NOW - timedelta(days=3))
    check_in(db, noa, staff, NOW - timedelta(days=1))

    rows = search_customers(db).rows
    assert [(row.customer.first_name, row.last_check_in_at) for row in rows] == [
        ("Dan", None),
        ("Noa", NOW - timedelta(days=1)),
    ]


def test_filters_and_text_combine(db: Session, staff: StaffUser) -> None:
    dana_c = add(db, "דנה", "כהן", "+972501111111")
    dana_l = add(db, "דנה", "לוי", "+972502222222")
    add(db, "יעל", "כהן", "+972503333333")
    check_in(db, dana_c, staff, NOW)

    assert found(db, text="דנה", came_in=CameIn.LAST_7_DAYS) == [dana_c]
    assert found(db, text="דנה", came_in=CameIn.NOT_IN_30_DAYS) == [dana_l]


# --- Sorting -------------------------------------------------------------


def test_sorting_by_last_check_in(db: Session, staff: StaffUser) -> None:
    never_b = add(db, "B", "Never", "+972501111111")
    never_a = add(db, "A", "Never", "+972502222222")
    old = add(db, "C", "Old", "+972503333333")
    recent = add(db, "D", "Recent", "+972504444444")
    check_in(db, old, staff, NOW - timedelta(days=40))
    check_in(db, recent, staff, NOW - timedelta(days=1))

    assert found(db, sort=SortBy.LAST_CHECK_IN) == [recent, old, never_a, never_b]


# --- Paging --------------------------------------------------------------


def test_pages_split_the_list(db: Session) -> None:
    everyone = [add(db, f"N{i:02}", "X", f"+9725011111{i:02}") for i in range(5)]

    first = search_customers(db, page_size=2)
    last = search_customers(db, page=3, page_size=2)

    assert [row.customer for row in first.rows] == everyone[:2]
    assert (first.total, first.page, first.page_count) == (5, 1, 3)
    assert [row.customer for row in last.rows] == everyone[4:]
    assert last.page == 3


def test_the_total_counts_only_matches(db: Session) -> None:
    for i in range(3):
        add(db, "דנה", f"X{i}", f"+97250111111{i}")
    add(db, "יעל", "Y", "+972502222222")

    page = search_customers(db, text="דנה", page_size=2)

    assert (page.total, page.page_count) == (3, 2)


def test_a_page_past_the_end_answers_the_last_page(db: Session) -> None:
    everyone = [add(db, f"N{i}", "X", f"+97250111111{i}") for i in range(3)]

    page = search_customers(db, page=9, page_size=2)

    assert page.page == 2
    assert [row.customer for row in page.rows] == everyone[2:]


def test_an_empty_list_is_page_1_of_1(db: Session) -> None:
    page = search_customers(db, page=4)

    assert (page.rows, page.total, page.page, page.page_count) == ([], 0, 1, 1)


@pytest.mark.parametrize(("page", "size"), [(0, 25), (1, 0)])
def test_pages_start_at_1(db: Session, page: int, size: int) -> None:
    with pytest.raises(ValueError):
        search_customers(db, page=page, page_size=size)
