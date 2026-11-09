"""The customer list: searching by name or phone, filtering by recent
check-ins, sorting and paging (design doc "Users and roles"; decision 0037).

Only reads. The search text is a name search unless it's only digits and
phone separators, which makes it a phone search:

- **Name:** every word must appear somewhere in the first or the last name
  ("דנה כה" finds דנה כהן). Latin letters match in either case. ``%`` and
  ``_`` are plain characters, not wildcards.
- **Phone:** the digits must appear in the number as it's written in Israel
  (``0501234567``), so the last four digits are enough. A number typed with
  the country code (``+972 50…``) is read as its local form.

The "came in" filter and the last-visit sort use each customer's latest
check-in, by any method. Its days are Israel days: "the last 7 days" is
today and the 6 days before it.

Paging is by page number. Customers are added rarely, so pages don't shift
while someone reads them (the activity log, which grows all the time, pages
by id instead). A page past the end answers with the last page.
"""

import math
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, String, and_, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.clock import to_local, utc_now
from app.core.config import get_settings
from app.core.models import CheckIn, Customer

PAGE_SIZE = 25
# The text is cut here: no name or number is anywhere near this long.
SEARCH_MAX_LENGTH = 100

# Typed or pasted between a number's digits (as in customers.py), plus "+".
_PHONE_SEPARATORS = frozenset("-.()/+")
_LIKE_ESCAPE = "\\"


class CameIn(StrEnum):
    """Which customers, by their latest check-in. The values are the API's."""

    ANY = "any"
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"
    # Including customers who never checked in.
    NOT_IN_30_DAYS = "not_30d"


class SortBy(StrEnum):
    """The list's order. The values are the API's."""

    # First name, then last name.
    NAME = "name"
    # The latest check-in first; customers who never came in last.
    LAST_CHECK_IN = "last_check_in"


@dataclass(frozen=True)
class CustomerRow:
    customer: Customer
    # UTC; ``None`` if they never checked in.
    last_check_in_at: datetime | None


@dataclass(frozen=True)
class CustomerPage:
    rows: list[CustomerRow]
    # Every customer the search and filters match, on all pages.
    total: int
    # 1-based; the page actually answered, after a page past the end.
    page: int
    page_size: int

    @property
    def page_count(self) -> int:
        """At least 1, so an empty list is "page 1 of 1"."""
        return max(1, math.ceil(self.total / self.page_size))


def search_customers(
    db: Session,
    *,
    active: bool = True,
    text: str = "",
    came_in: CameIn = CameIn.ANY,
    sort: SortBy = SortBy.NAME,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> CustomerPage:
    """One page of the active (or only the inactive) customers that match.

    An empty ``text`` matches everyone. ``page`` and ``page_size`` start at
    1; anything lower raises ``ValueError``.
    """
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size start at 1")

    latest = (
        select(
            CheckIn.customer_id,
            func.max(CheckIn.checked_in_at).label("at"),
        )
        .group_by(CheckIn.customer_id)
        .subquery()
    )
    matching: Select = (
        select(Customer, latest.c.at)
        .outerjoin(latest, latest.c.customer_id == Customer.id)
        .where(Customer.active.is_(active), *_text_conditions(text))
    )
    if came_in is not CameIn.ANY:
        matching = matching.where(_came_in_condition(came_in, latest.c.at))

    total = db.scalar(select(func.count()).select_from(matching.subquery())) or 0
    page = min(page, max(1, math.ceil(total / page_size)))

    by_name = (Customer.first_name, Customer.last_name, Customer.id)
    order = (
        by_name if sort is SortBy.NAME else (latest.c.at.desc().nulls_last(), *by_name)
    )
    found = db.execute(
        matching.order_by(*order).limit(page_size).offset((page - 1) * page_size)
    )
    return CustomerPage(
        rows=[CustomerRow(customer, at) for customer, at in found],
        total=total,
        page=page,
        page_size=page_size,
    )


def _text_conditions(text: str) -> list[ColumnElement[bool]]:
    # NFKC turns full-width digits and letters into plain ones; invisible
    # direction marks (common in text copied out of Hebrew) are dropped.
    cleaned = "".join(
        char
        for char in unicodedata.normalize("NFKC", text[:SEARCH_MAX_LENGTH])
        if unicodedata.category(char) != "Cf"
    )
    digits = _phone_digits(cleaned)
    if digits is not None:
        # The stored form is "+972" and the number without its 0.
        written = literal("0", String) + func.substr(Customer.phone, 5, type_=String)
        return [written.like(_contains(digits), escape=_LIKE_ESCAPE)]
    return [
        or_(
            func.lower(Customer.first_name).like(
                _contains(word.lower()), escape=_LIKE_ESCAPE
            ),
            func.lower(Customer.last_name).like(
                _contains(word.lower()), escape=_LIKE_ESCAPE
            ),
        )
        for word in cleaned.split()
    ]


def _phone_digits(text: str) -> str | None:
    """The digits to look for, as the number is written locally, if
    ``text`` is a phone search; ``None`` if it's a name search (or empty)."""
    kept = "".join(
        char for char in text if not (char.isspace() or char in _PHONE_SEPARATORS)
    )
    if not kept or not kept.isascii() or not kept.isdigit():
        return None
    # "972" is a country code when "+" or "00" says so, or when a whole
    # number follows it; otherwise it's three digits from inside a number.
    country_code_typed = text.lstrip().startswith("+") or kept.startswith("00972")
    for country_code in ("00972", "972"):
        rest = kept.removeprefix(country_code)
        if rest != kept and (country_code_typed or len(rest.lstrip("0")) >= 8):
            # "+972 050…" (the local 0 kept by mistake) is the same number.
            return "0" + kept.removeprefix(country_code).removeprefix("0")
    return kept


def _contains(value: str) -> str:
    escaped = (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _came_in_condition(came_in: CameIn, latest_at) -> ColumnElement[bool]:
    days = 7 if came_in is CameIn.LAST_7_DAYS else 30
    since = _start_of_days_ago(days - 1)
    if came_in is CameIn.NOT_IN_30_DAYS:
        return or_(latest_at.is_(None), latest_at < since)
    return and_(latest_at.is_not(None), latest_at >= since)


def _start_of_days_ago(days: int) -> datetime:
    """The UTC moment the local (Israel) day ``days`` days before today
    started."""
    today = to_local(utc_now()).date()
    start = datetime.combine(today - timedelta(days=days), time(), get_settings().tz)
    return start.astimezone(UTC)
