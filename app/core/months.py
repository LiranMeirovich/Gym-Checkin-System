"""A calendar month, the unit prices and plans work in (design doc: "Plans,
prices and billing"; decision 0022).

A month can't hold a day, so "valid from the 15th" can't be expressed. Its
one text form is ``YYYY-MM``: that's what the database and the API carry, and
sorting the text gives the same order as the months.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Self

from app.core.clock import to_local, utc_now

_TEXT_FORM = re.compile(r"[0-9]{4}-[0-9]{2}")


@dataclass(frozen=True, order=True)
class Month:
    """One calendar month. Compares by time: January comes before March."""

    year: int
    month: int

    def __post_init__(self) -> None:
        # Four digits, or sorting the text form would stop matching the time.
        if not 1000 <= self.year <= 9999:
            raise ValueError("a month's year has four digits")
        if not 1 <= self.month <= 12:
            raise ValueError("a month is 1 to 12")

    @classmethod
    def parse(cls, text: str) -> Self:
        """The month written as ``YYYY-MM``. Raises ``ValueError``."""
        if not _TEXT_FORM.fullmatch(text):
            raise ValueError("a month is written YYYY-MM")
        return cls(int(text[:4]), int(text[5:]))

    @classmethod
    def of(cls, day: date) -> Self:
        """The month ``day`` falls in."""
        return cls(day.year, day.month)

    @classmethod
    def current(cls) -> Self:
        """This month at the gym, not in UTC: the two differ for a few hours
        around every month's start."""
        return cls.of(to_local(utc_now()).date())

    def plus(self, months: int) -> Self:
        """The month ``months`` later (earlier, if negative)."""
        years, month_index = divmod(self.year * 12 + self.month - 1 + months, 12)
        return type(self)(years, month_index + 1)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"
