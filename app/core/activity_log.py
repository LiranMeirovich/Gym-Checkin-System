"""Writing to the activity log: who changed what, from what, to what
(design doc: "Activity log").

Every staff change calls ``record()`` in the same transaction as the change
itself, so either both are saved or neither is. A few sensitive reads are
recorded too (opening a health form's contents, milestone 3). Logins and
locking aren't; ``staff_sessions`` is the login history.

This module only adds rows. Nothing in the app changes or deletes one, and
the database refuses to (triggers on ``activity_log``). ``list_entries()``
reads them for the manager's log screen.

Never put a secret in ``before`` or ``after``: no PINs, PIN hashes, tokens
or passwords. A change to one is recorded without its values.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import start_of_local_day
from app.core.models import ActivityLogEntry, Customer, StaffUser


class Action(StrEnum):
    """Every kind of change, named ``<area>.<verb>``. The values are what
    ``activity_log.action`` stores, so never rename one: old rows keep the
    old name."""

    STAFF_CREATE = "staff.create"
    STAFF_RESET_PIN = "staff.reset_pin"
    STAFF_CHANGE_ROLE = "staff.change_role"
    STAFF_DEACTIVATE = "staff.deactivate"
    STAFF_REACTIVATE = "staff.reactivate"

    SETTINGS_UPDATE = "settings.update"

    CUSTOMER_CREATE = "customer.create"
    # Name, phone and notes.
    CUSTOMER_EDIT = "customer.edit"
    CUSTOMER_CHANGE_DATE_OF_BIRTH = "customer.change_date_of_birth"
    CUSTOMER_DEACTIVATE = "customer.deactivate"
    CUSTOMER_REACTIVATE = "customer.reactivate"

    PRICE_ADD = "price.add"

    PLAN_CHOOSE = "plan.choose"
    # A choice replaced by another plan, or cleared by a "no plan" row.
    PLAN_CORRECT = "plan.correct"
    PLAN_CLEAR = "plan.clear"

    # The manager bought a punch card for a customer at a manual check-in.
    # A customer's own purchase on their phone isn't logged.
    PUNCH_CARD_BUY = "punch_card.buy"

    # The manager generated (or regenerated) a month's report.
    REPORT_GENERATE = "report.generate"

    # A link code for a customer's phone (never the code itself).
    PHONE_ISSUE_CODE = "phone.issue_code"
    PHONE_UNLINK = "phone.unlink"

    # The manager opened a health form's contents (its PDF).
    HEALTH_FORM_OPEN = "health_form.open"
    # Staff added a doctor's note to a form with a "yes" (never the image).
    HEALTH_FORM_ADD_DOCTOR_NOTE = "health_form.add_doctor_note"
    # The manager accepted a form with a "yes" without a doctor's note
    # (decision 0041).
    HEALTH_FORM_ACCEPT = "health_form.accept"
    # Staff opened the form on the admin PC and the customer signed it
    # there (never the answers).
    HEALTH_FORM_FILL_IN = "health_form.fill_in"
    # The manager opened a doctor's note (its image).
    DOCTOR_NOTE_OPEN = "doctor_note.open"

    # A staff member checked a customer in at the desk. A repeat within
    # the 10-minute window records nothing, so it isn't logged.
    CHECKIN_MANUAL = "checkin.manual"


class Target(StrEnum):
    """What kind of thing a change was made to; ``activity_log.target_type``.
    Never rename one either."""

    STAFF_USER = "staff_user"
    # The gym settings as a whole: no target id, the keys are in
    # before/after.
    SETTINGS = "settings"
    CUSTOMER = "customer"
    PRICE = "price"
    PLAN_CHOICE = "plan_choice"
    PUNCH_CARD = "punch_card"
    DEVICE_SESSION = "device_session"
    HEALTH_FORM = "health_form"
    DOCTOR_NOTE = "doctor_note"
    CHECKIN = "checkin"
    REPORT = "report"


def record(
    db: Session,
    actor: StaffUser,
    action: Action,
    target_type: Target,
    target_id: int | None = None,
    *,
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
) -> ActivityLogEntry:
    """Add a log entry: ``actor`` did ``action`` to the target, changing
    ``before`` into ``after``. Works in the caller's transaction and never
    commits.

    ``before`` and ``after`` hold only plain JSON values (text, numbers,
    booleans, None, lists, dicts). Anything else, such as a datetime, is a
    ``TypeError``: the caller decides how it should read in the log.
    """
    if actor.id is None:
        # A staff member created in this transaction gets an id on flush;
        # the staff functions flush before they record.
        raise ValueError("the actor has no id yet; flush it first")
    entry = ActivityLogEntry(
        staff_user_id=actor.id,
        action=Action(action),
        target_type=Target(target_type),
        target_id=target_id,
        before_json=_to_json(before),
        after_json=_to_json(after),
    )
    db.add(entry)
    db.flush()
    return entry


PAGE_SIZE = 50

# The dates a filter may use. Far wider than the log will ever span, and far
# enough from date.min/max that turning a local day into UTC can't overflow.
EARLIEST_DATE = date(2000, 1, 1)
LATEST_DATE = date(2999, 12, 31)


class InvalidLogFilterError(ValueError):
    """The filters can't be used: a ``target_id`` without a
    ``target_type``, or a date outside EARLIEST_DATE..LATEST_DATE."""


@dataclass(frozen=True)
class LogEntry:
    """One entry as the log screen shows it.

    ``action`` and ``target_type`` are the stored text, not the enums, and
    ``before``/``after`` are the stored JSON as it was written: older entries
    keep older shapes (decision 0021), and the screen copes with any.
    """

    id: int
    at: datetime
    staff_user_id: int
    staff_name: str
    action: str
    target_type: str
    target_id: int | None
    # The target's name, for a staff member or a customer; None for the rest.
    target_name: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class LogPage:
    entries: list[LogEntry]
    # Pass as ``before_id`` for the next (older) page; None on the last one.
    next_before_id: int | None


def list_entries(
    db: Session,
    *,
    staff_user_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    before_id: int | None = None,
    limit: int = PAGE_SIZE,
) -> LogPage:
    """The log, newest first, one page at a time.

    The dates are local (Israel) days, both included. ``before_id`` pages by
    id rather than by offset, so entries added while the manager reads don't
    shift the pages. ``target_id`` needs a ``target_type``; anything else
    raises ``InvalidLogFilterError``.
    """
    if target_id is not None and target_type is None:
        raise InvalidLogFilterError("target_id needs a target_type")
    for day in (from_date, to_date):
        if day is not None and not EARLIEST_DATE <= day <= LATEST_DATE:
            raise InvalidLogFilterError(f"date out of range: {day}")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    query = (
        select(ActivityLogEntry, StaffUser.display_name)
        .join(StaffUser, StaffUser.id == ActivityLogEntry.staff_user_id)
        .order_by(ActivityLogEntry.id.desc())
        # One more than asked, to know whether there's another page.
        .limit(limit + 1)
    )
    if staff_user_id is not None:
        query = query.where(ActivityLogEntry.staff_user_id == staff_user_id)
    if from_date is not None:
        query = query.where(ActivityLogEntry.at >= start_of_local_day(from_date))
    if to_date is not None:
        query = query.where(
            ActivityLogEntry.at < start_of_local_day(to_date + timedelta(days=1))
        )
    if target_type is not None:
        query = query.where(ActivityLogEntry.target_type == target_type)
    if target_id is not None:
        query = query.where(ActivityLogEntry.target_id == target_id)
    if before_id is not None:
        query = query.where(ActivityLogEntry.id < before_id)

    rows = db.execute(query).all()
    more = len(rows) > limit
    rows = rows[:limit]
    names = _target_names(db, [entry for entry, _ in rows])
    entries = [
        LogEntry(
            id=entry.id,
            at=entry.at,
            staff_user_id=entry.staff_user_id,
            staff_name=staff_name,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            target_name=names.get((entry.target_type, entry.target_id)),
            before=_from_json(entry.before_json),
            after=_from_json(entry.after_json),
        )
        for entry, staff_name in rows
    ]
    return LogPage(entries, entries[-1].id if more else None)


def _target_names(
    db: Session, entries: list[ActivityLogEntry]
) -> dict[tuple[str, int | None], str]:
    """Names for the staff and customer targets on a page, two queries in all."""

    def ids(target: Target) -> set[int]:
        return {
            e.target_id
            for e in entries
            if e.target_type == target and e.target_id is not None
        }

    names: dict[tuple[str, int | None], str] = {}
    staff_ids = ids(Target.STAFF_USER)
    if staff_ids:
        for staff_id, name in db.execute(
            select(StaffUser.id, StaffUser.display_name).where(
                StaffUser.id.in_(staff_ids)
            )
        ):
            names[(Target.STAFF_USER, staff_id)] = name
    customer_ids = ids(Target.CUSTOMER)
    if customer_ids:
        for customer_id, first, last in db.execute(
            select(Customer.id, Customer.first_name, Customer.last_name).where(
                Customer.id.in_(customer_ids)
            )
        ):
            names[(Target.CUSTOMER, customer_id)] = f"{first} {last}"
    return names


def _from_json(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    value = json.loads(text)
    # record() only writes objects, but a hand-written or older row might
    # hold something else; keep it visible rather than failing the page.
    return value if isinstance(value, dict) else {"value": value}


def _to_json(values: Mapping[str, object] | None) -> str | None:
    if values is None:
        return None
    # ensure_ascii=False keeps Hebrew readable in a database browser.
    # sort_keys, so the same change is always written the same way.
    # allow_nan=False: NaN isn't JSON, and json_valid() would refuse it.
    return json.dumps(dict(values), ensure_ascii=False, sort_keys=True, allow_nan=False)
