"""Customers: adding, editing, changing the date of birth, deactivating
and reactivating them (design doc: "Users and roles", "Data model";
decisions 0021, 0023).

A phone number is one person, always. It's normalised to one stored form
(``normalise_phone``), and it's unique across every customer, active or
not: adding someone whose phone belongs to an inactive customer brings
that customer back instead of making a second one. Customers are never
deleted; deactivating only hides them from the default list.

Every function works inside the caller's transaction and never commits.
Every change is written to the activity log in the same transaction, with
``by``, the staff member making it, as the actor; a change that changes
nothing writes no entry. Whether ``by`` may make the change is the route's
check (``require_permission``), not this module's.
"""

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target, record
from app.core.clock import to_local, utc_now
from app.core.models import Customer, StaffUser

NAME_MAX_LENGTH = 50
NOTES_MAX_LENGTH = 256
# Anyone older is a typo in the year.
MAX_AGE_YEARS = 120

# The customer's number without its leading 0, by its first digit: 05x
# mobiles and 07x numbers have 9 digits, landlines (02, 03, 04, 08, 09)
# have 8. Anything else (1-800 numbers, 06) isn't a customer's phone.
_NATIONAL_LENGTHS = {"5": 9, "7": 9, "2": 8, "3": 8, "4": 8, "8": 8, "9": 8}
# Typed or pasted between the digits; removed before checking.
_PHONE_SEPARATORS = frozenset("-.()/")


class CustomerField(StrEnum):
    """The fields a refused change can name."""

    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    PHONE = "phone"
    DATE_OF_BIRTH = "date_of_birth"
    NOTES = "notes"


class InvalidCustomerError(ValueError):
    """One or more fields break their rule. ``fields`` lists every one of
    them at once, so a form can mark them all. Nothing was saved."""

    def __init__(self, fields: set[CustomerField]) -> None:
        super().__init__("invalid: " + ", ".join(sorted(fields)))
        self.fields = frozenset(fields)


class PhoneTakenError(ValueError):
    """The phone belongs to another customer: an active one when adding,
    any other one when editing. ``customer`` is that customer, so staff
    can open their page."""

    def __init__(self, customer: Customer) -> None:
        super().__init__(f"the phone belongs to customer {customer.id}")
        self.customer = customer


class CustomerInactiveError(ValueError):
    """An inactive customer can't be edited; reactivate them first."""


class InvalidPhoneError(ValueError):
    """Not an Israeli phone number in any form ``normalise_phone`` knows."""


@dataclass(frozen=True)
class Added:
    """What ``add_customer`` did. ``reactivated`` means the phone belonged
    to an inactive customer, who is now active again, unchanged: the
    form's other details were not applied."""

    customer: Customer
    reactivated: bool


def normalise_phone(text: str) -> str:
    """The one stored form of an Israeli phone number (E.164,
    ``+972501234567``), however it was typed: ``050-123 4567``,
    ``+972 50 123 4567``, ``972501234567``, ``00972-50-1234567`` and
    ``+972 050…`` are all the same number. Raises ``InvalidPhoneError``.

    Israel is assumed as the country (decision 0023).
    """
    # NFKC turns full-width digits into plain ones. Spaces, separators and
    # invisible direction marks (which copying a number out of Hebrew text
    # often adds) are dropped.
    kept = "".join(
        char
        for char in unicodedata.normalize("NFKC", text)
        if not (
            char.isspace()
            or char in _PHONE_SEPARATORS
            or unicodedata.category(char) == "Cf"
        )
    )
    for country_code in ("+972", "00972", "972"):
        if kept.startswith(country_code):
            # "+972 050…": the local 0 kept by mistake.
            national = kept.removeprefix(country_code).removeprefix("0")
            break
    else:
        if not kept.startswith("0"):
            raise InvalidPhoneError("not an Israeli phone number")
        national = kept[1:]
    if not national or any(char not in "0123456789" for char in national):
        raise InvalidPhoneError("a phone number is digits only")
    if _NATIONAL_LENGTHS.get(national[0]) != len(national):
        raise InvalidPhoneError("not an Israeli phone number")
    return "+972" + national


def find_by_phone(db: Session, phone: str) -> Customer | None:
    """The customer with this phone, active or not, in any typed form.
    ``None`` if nobody has it or it isn't a valid number."""
    try:
        stored = normalise_phone(phone)
    except InvalidPhoneError:
        return None
    return db.scalar(select(Customer).where(Customer.phone == stored))


def list_customers(db: Session, *, active: bool = True) -> list[Customer]:
    """Active (or only inactive) customers, by first and then last name."""
    return list(
        db.scalars(
            select(Customer)
            .where(Customer.active.is_(active))
            .order_by(Customer.first_name, Customer.last_name, Customer.id)
        )
    )


def add_customer(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    date_of_birth: date,
    notes: str = "",
    by: StaffUser,
) -> Added:
    """Add a customer. If the phone belongs to an inactive customer, that
    customer is reactivated instead (``Added.reactivated``).

    Raises ``InvalidCustomerError`` (every invalid field) or
    ``PhoneTakenError`` (an active customer has the phone).
    """
    values = _clean(
        {
            CustomerField.FIRST_NAME: first_name,
            CustomerField.LAST_NAME: last_name,
            CustomerField.PHONE: phone,
            CustomerField.DATE_OF_BIRTH: date_of_birth,
            CustomerField.NOTES: notes,
        }
    )
    owner = db.scalar(select(Customer).where(Customer.phone == values["phone"]))
    if owner is not None:
        if owner.active:
            raise PhoneTakenError(owner)
        reactivate_customer(db, owner, by=by)
        return Added(owner, reactivated=True)

    customer = Customer(**values)
    db.add(customer)
    db.flush()
    record(
        db,
        by,
        Action.CUSTOMER_CREATE,
        Target.CUSTOMER,
        customer.id,
        after=_loggable({**values, "active": customer.active}),
    )
    return Added(customer, reactivated=False)


def edit_customer(
    db: Session,
    customer: Customer,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    by: StaffUser,
) -> None:
    """Change any of the name, phone and notes; ``None`` leaves a field as
    it is. The date of birth has its own function (manager only).

    Raises ``CustomerInactiveError``, ``InvalidCustomerError`` or
    ``PhoneTakenError`` (any other customer has the phone, active or not:
    two records can't become one person).
    """
    given = {
        field: value
        for field, value in {
            CustomerField.FIRST_NAME: first_name,
            CustomerField.LAST_NAME: last_name,
            CustomerField.PHONE: phone,
            CustomerField.NOTES: notes,
        }.items()
        if value is not None
    }
    _ensure_active(customer)
    values = _clean(given)
    if "phone" in values:
        owner = db.scalar(
            select(Customer).where(
                Customer.phone == values["phone"], Customer.id != customer.id
            )
        )
        if owner is not None:
            raise PhoneTakenError(owner)
    _apply(db, customer, values, Action.CUSTOMER_EDIT, by=by)


def change_date_of_birth(
    db: Session, customer: Customer, date_of_birth: date, *, by: StaffUser
) -> None:
    """Correct the date of birth, which sets the under-18 price. Raises
    ``CustomerInactiveError`` or ``InvalidCustomerError``."""
    _ensure_active(customer)
    values = _clean({CustomerField.DATE_OF_BIRTH: date_of_birth})
    _apply(db, customer, values, Action.CUSTOMER_CHANGE_DATE_OF_BIRTH, by=by)


def deactivate_customer(db: Session, customer: Customer, *, by: StaffUser) -> None:
    """Hide the customer from the default list. Nothing else changes."""
    if not customer.active:
        return
    _apply(db, customer, {"active": False}, Action.CUSTOMER_DEACTIVATE, by=by)


def reactivate_customer(db: Session, customer: Customer, *, by: StaffUser) -> None:
    """Bring an inactive customer back, with their history."""
    if customer.active:
        return
    _apply(db, customer, {"active": True}, Action.CUSTOMER_REACTIVATE, by=by)


def _apply(
    db: Session,
    customer: Customer,
    values: Mapping[str, object],
    action: Action,
    *,
    by: StaffUser,
) -> None:
    # Only the fields that really change, in the row and in the log.
    before = {
        field: getattr(customer, field)
        for field, value in values.items()
        if getattr(customer, field) != value
    }
    if not before:
        return
    after = {field: values[field] for field in before}
    for field, value in after.items():
        setattr(customer, field, value)
    db.flush()
    record(
        db,
        by,
        action,
        Target.CUSTOMER,
        customer.id,
        before=_loggable(before),
        after=_loggable(after),
    )


def _ensure_active(customer: Customer) -> None:
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")


def _clean(given: Mapping[CustomerField, object]) -> dict[str, object]:
    """Each given field in its stored form. Raises ``InvalidCustomerError``
    naming every field that breaks its rule."""
    values: dict[str, object] = {}
    invalid: set[CustomerField] = set()
    for field, value in given.items():
        try:
            values[field.value] = _CLEANERS[field](value)
        except ValueError:
            invalid.add(field)
    if invalid:
        raise InvalidCustomerError(invalid)
    return values


def _clean_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("a name is text")
    # NFC, so the same letters typed two ways are stored the same, and runs
    # of spaces become one.
    name = " ".join(unicodedata.normalize("NFC", value).split())
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        raise ValueError(f"a name is 1 to {NAME_MAX_LENGTH} characters")
    # Control, format (zero-width, direction marks) and unassigned
    # characters are invisible and would make two names look the same.
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise ValueError("a name can't contain invisible characters")
    return name


def _clean_phone(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("a phone number is text")
    return normalise_phone(value)


def _clean_date_of_birth(value: object) -> date:
    # A datetime is a date too, but would be stored with a time.
    if not isinstance(value, date) or hasattr(value, "hour"):
        raise ValueError("a date of birth is a date")
    today = to_local(utc_now()).date()
    if value > today or today.year - value.year > MAX_AGE_YEARS:
        raise ValueError("not a believable date of birth")
    return value


def _clean_notes(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("notes are text")
    notes = unicodedata.normalize("NFC", value).replace("\r\n", "\n").strip()
    if len(notes) > NOTES_MAX_LENGTH:
        raise ValueError(f"notes are at most {NOTES_MAX_LENGTH} characters")
    # Line breaks are fine; other control and invisible characters aren't.
    if any(
        unicodedata.category(char).startswith("C") and char != "\n" for char in notes
    ):
        raise ValueError("notes can't contain invisible characters")
    return notes


_CLEANERS = {
    CustomerField.FIRST_NAME: _clean_name,
    CustomerField.LAST_NAME: _clean_name,
    CustomerField.PHONE: _clean_phone,
    CustomerField.DATE_OF_BIRTH: _clean_date_of_birth,
    CustomerField.NOTES: _clean_notes,
}


def _loggable(values: Mapping[str, object]) -> dict[str, object]:
    # The log holds plain JSON: a date is written as YYYY-MM-DD.
    return {
        field: value.isoformat() if isinstance(value, date) else value
        for field, value in values.items()
    }
