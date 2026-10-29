"""Writing to the activity log: who changed what, from what, to what
(design doc: "Activity log").

Every staff change calls ``record()`` in the same transaction as the change
itself, so either both are saved or neither is. A few sensitive reads are
recorded too (opening a health form's contents, milestone 3). Logins and
locking aren't; ``staff_sessions`` is the login history.

This module only adds rows. Nothing in the app changes or deletes one, and
the database refuses to (triggers on ``activity_log``).

Never put a secret in ``before`` or ``after``: no PINs, PIN hashes, tokens
or passwords. A change to one is recorded without its values.
"""

import json
from collections.abc import Mapping
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.models import ActivityLogEntry, StaffUser


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


class Target(StrEnum):
    """What kind of thing a change was made to; ``activity_log.target_type``.
    Never rename one either."""

    STAFF_USER = "staff_user"
    # The gym settings as a whole: no target id, the keys are in
    # before/after.
    SETTINGS = "settings"
    CUSTOMER = "customer"


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


def _to_json(values: Mapping[str, object] | None) -> str | None:
    if values is None:
        return None
    # ensure_ascii=False keeps Hebrew readable in a database browser.
    # sort_keys, so the same change is always written the same way.
    # allow_nan=False: NaN isn't JSON, and json_valid() would refuse it.
    return json.dumps(dict(values), ensure_ascii=False, sort_keys=True, allow_nan=False)
