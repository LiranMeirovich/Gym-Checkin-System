"""Request and response shapes of the admin API. The frontend's TypeScript
types are generated from these (through the OpenAPI spec), so a change
here that breaks the frontend fails its build."""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.core.models import AgeGroup, Plan
from app.core.permissions import Role

# SQLite's integer range. A bigger id can't exist, and SQLite would refuse
# to look it up (a 500), so it's refused as a malformed request instead.
MAX_ID = 2**63 - 1


class Answer(BaseModel):
    """Base for response shapes. Fields with a default are always sent, so
    the generated TypeScript types mark them required, not optional."""

    model_config = ConfigDict(
        json_schema_mode_override="serialization",
        json_schema_serialization_defaults_required=True,
    )


class NotLoggedIn(Answer):
    """401 from any route that needs a login: no session, or it ended or
    timed out. ``setup_needed`` says to go to first-run setup instead of
    the lock screen."""

    detail: Literal["not_logged_in"] = "not_logged_in"
    setup_needed: bool


# ── The lock screen ─────────────────────────────────────────────────────


class StaffName(Answer):
    id: int
    display_name: str


class LockScreen(Answer):
    """The names to tap; empty with ``setup_needed`` on a fresh install."""

    setup_needed: bool
    staff: list[StaffName]


class LoginRequest(BaseModel):
    staff_id: int = Field(ge=1, le=MAX_ID)
    # Real PINs are 6-12 digits; the cap only keeps a huge value away from
    # the (deliberately slow) PIN check.
    pin: str = Field(max_length=100)


LoginRefusal = Literal["wrong_pin", "locked", "no_such_staff"]


class LoginRefused(Answer):
    """401 from ``POST /api/login``. ``locked_until`` (the gym's local
    time, with its offset) comes with ``locked`` only."""

    error: LoginRefusal
    locked_until: datetime | None = None


# ── A logged-in session ─────────────────────────────────────────────────


class StaffInfo(Answer):
    id: int
    display_name: str
    role: Role


class SessionInfo(Answer):
    """Who is logged in, plus what the page needs to act for them: the
    CSRF token for the ``X-CSRF-Token`` header (kept in memory only) and
    the idle time after which the page goes to the lock screen."""

    staff: StaffInfo
    csrf_token: str
    lock_after_seconds: int


# ── First-run setup ─────────────────────────────────────────────────────


class SetupStatus(Answer):
    needed: Literal[True] = True


class SetupRequest(BaseModel):
    gym_name: str
    display_name: str
    pin: str
    pin_again: str


SetupField = Literal["gym_name", "display_name", "pin", "pin_again"]
SetupProblem = Literal["invalid", "mismatch"]


class SetupRefused(Answer):
    """400 from ``POST /api/setup``: every field with a problem, at once.
    ``invalid`` breaks that field's rule; ``mismatch`` is ``pin_again``
    differing from ``pin``. Nothing was saved."""

    errors: dict[SetupField, SetupProblem]


# ── Customers ───────────────────────────────────────────────────────────
# The caps on text only keep a huge value out; the real rules (names 1-50
# characters, notes up to 256, an Israeli phone) are app.core.customers',
# which answers a broken one with a field code, not a 422.

CustomerField = Literal["first_name", "last_name", "phone", "date_of_birth", "notes"]
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _iso_date_text(value: object) -> object:
    # Pydantic would also take a number (a Unix time) or a date-time with
    # a zero time; a date of birth is only ever "YYYY-MM-DD".
    if not (isinstance(value, str) and _ISO_DATE.fullmatch(value)):
        raise ValueError("a date is YYYY-MM-DD")
    return value


DateOfBirth = Annotated[date, BeforeValidator(_iso_date_text)]


class CustomerSummary(Answer):
    """A row of the customer list. ``phone`` is the stored E.164 form
    (``+972501234567``); React formats it for display."""

    id: int
    first_name: str
    last_name: str
    phone: str
    active: bool


class CustomerList(Answer):
    customers: list[CustomerSummary]


class CustomerDetails(CustomerSummary):
    """One customer's page. ``created_at`` is the gym's local time, with
    its offset."""

    date_of_birth: date
    notes: str
    created_at: datetime


class NewCustomer(BaseModel):
    first_name: str = Field(max_length=200)
    last_name: str = Field(max_length=200)
    phone: str = Field(max_length=50)
    date_of_birth: DateOfBirth
    notes: str = Field(default="", max_length=2000)


class CustomerAdded(Answer):
    """201 from ``POST /api/customers``. ``reactivated``: the phone was an
    inactive customer's, who is active again with their own details (the
    form's others weren't applied)."""

    customer: CustomerDetails
    reactivated: bool


class CustomerEdit(BaseModel):
    """Only the fields sent are changed; the date of birth has its own
    route (manager only)."""

    first_name: str | None = Field(default=None, max_length=200)
    last_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class DateOfBirthChange(BaseModel):
    date_of_birth: DateOfBirth


class CustomerRefused(Answer):
    """400: every field that breaks its rule, at once. Nothing was
    saved."""

    errors: dict[CustomerField, Literal["invalid"]]


class CustomerConflict(Answer):
    """409. ``phone_taken``: another customer has the phone, and
    ``customer_id`` says who, so staff can open their page.
    ``customer_inactive``: reactivate the customer before editing."""

    error: Literal["phone_taken", "customer_inactive"]
    customer_id: int | None = None


# ── Prices ──────────────────────────────────────────────────────────────
# Amounts are whole agorot; React shows and reads shekels. The real limits
# and which months can be chosen are app.core.prices', which answers a broken
# one with a field code, not a 422.

# Four digits from 1000 on, then 01-12: exactly what ``Month.parse`` accepts.
MonthText = Annotated[str, Field(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$")]


class PriceInEffect(Answer):
    """One cell of the price table. Both are ``None`` if it's not set yet."""

    plan: Plan
    age_group: AgeGroup
    amount_agorot: int | None
    valid_from_month: MonthText | None


class PriceRow(Answer):
    """A row as it was entered. ``created_at`` is the gym's local time, with
    its offset."""

    id: int
    plan: Plan
    age_group: AgeGroup
    amount_agorot: int
    valid_from_month: MonthText
    created_at: datetime


class PriceOverview(Answer):
    """``upcoming`` is the change waiting for each later month, soonest
    first. ``history`` is every row ever entered, latest month first."""

    current_month: MonthText
    current: list[PriceInEffect]
    upcoming: list[PriceRow]
    history: list[PriceRow]


class PriceChange(BaseModel):
    plan: Plan
    age_group: AgeGroup
    # Strict, so "100" and 100.0 are malformed rather than quietly converted.
    amount_agorot: int = Field(strict=True)


class PriceChanges(BaseModel):
    """All of them apply from one month, together or not at all."""

    valid_from_month: MonthText
    prices: list[PriceChange] = Field(max_length=50)


class PricesRefused(Answer):
    """400: every part that breaks its rule, at once: ``valid_from_month``,
    or a price as ``<plan>.<age_group>``. Nothing was saved."""

    errors: dict[str, Literal["invalid"]]
