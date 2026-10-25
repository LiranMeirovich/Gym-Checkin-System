"""Staff accounts: creating them, resetting PINs, changing roles,
deactivating, and checking a PIN with the lockout (design doc: "Staff login
and lock screen"; decision 0018).

These are the rules the database can't check on its own: there's always at
least one active manager, PINs follow the format rules, and 5 wrong PINs in
a row lock the account for 5 minutes. Every function works inside the
caller's transaction and never commits.

Who made a change isn't recorded yet. TODO(activity log): log every change
here (who, what, before and after) once the activity log exists.
"""

from datetime import timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.models import StaffUser
from app.core.permissions import Role
from app.core.pins import hash_pin, needs_rehash, pin_matches, rehash_pin

MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=5)
DISPLAY_NAME_MAX_LENGTH = 50


class InvalidDisplayNameError(ValueError):
    """The name is empty or too long."""


class DuplicateDisplayNameError(ValueError):
    """Another active staff member already has this name (ignoring case).
    Staff pick their name on the lock screen, so names must differ."""


class LastManagerError(ValueError):
    """The change would leave no active manager, and with it nobody who
    could manage staff, prices or settings."""


class PinCheck(StrEnum):
    """The outcome of ``check_pin``."""

    OK = "ok"
    WRONG_PIN = "wrong_pin"
    # Too many wrong PINs: either just now, or earlier and not over yet.
    # ``locked_until`` on the row says until when.
    LOCKED = "locked"
    INACTIVE = "inactive"


def create_staff_user(
    db: Session, display_name: str, role: Role, pin: str
) -> StaffUser:
    """Add an active staff member. Raises ``InvalidDisplayNameError``,
    ``DuplicateDisplayNameError`` or ``pins.InvalidPinError``."""
    name = _clean_display_name(display_name)
    _ensure_name_is_free(db, name)
    staff = StaffUser(display_name=name, role=Role(role), pin_hash=hash_pin(pin))
    db.add(staff)
    db.flush()
    return staff


def reset_pin(db: Session, staff: StaffUser, pin: str) -> None:
    """Give ``staff`` a new PIN. It also lifts a lockout, so a manager can
    let a locked-out instructor straight back in. Raises
    ``pins.InvalidPinError``."""
    staff.pin_hash = hash_pin(pin)
    staff.failed_attempts = 0
    staff.locked_until = None
    db.flush()


def change_role(db: Session, staff: StaffUser, role: Role) -> None:
    """Make ``staff`` a manager or an instructor. Raises
    ``LastManagerError`` if this demotes the last active manager."""
    role = Role(role)
    if role is not Role.MANAGER:
        _ensure_not_last_manager(db, staff)
    staff.role = role
    db.flush()


def deactivate(db: Session, staff: StaffUser) -> None:
    """Stop ``staff`` from logging in. The row stays, since other records
    point at it. Raises ``LastManagerError`` for the last active manager."""
    _ensure_not_last_manager(db, staff)
    staff.active = False
    db.flush()


def reactivate(db: Session, staff: StaffUser) -> None:
    """Let a deactivated staff member log in again. Raises
    ``DuplicateDisplayNameError`` if an active member took the name
    meanwhile."""
    if staff.active:
        return
    _ensure_name_is_free(db, staff.display_name)
    staff.active = True
    db.flush()


def check_pin(db: Session, staff: StaffUser, pin: str) -> PinCheck:
    """Check a login attempt and update the lockout counters.

    A locked or inactive account is refused without looking at the PIN,
    and that attempt doesn't count. A wrong PIN counts; the fifth in a row
    locks the account for ``LOCKOUT`` and starts the count again. A correct
    PIN clears the count, and replaces a hash made with older parameters.

    The counters are written in the caller's transaction, and a refused
    login must still commit them: a route that raises (and so rolls back)
    on a wrong PIN would make the lockout useless.
    """
    if not staff.active:
        return PinCheck.INACTIVE
    now = utc_now()
    if staff.locked_until is not None and staff.locked_until > now:
        return PinCheck.LOCKED

    if pin_matches(staff.pin_hash, pin):
        staff.failed_attempts = 0
        staff.locked_until = None
        if needs_rehash(staff.pin_hash):
            staff.pin_hash = rehash_pin(pin)
        db.flush()
        return PinCheck.OK

    staff.failed_attempts += 1
    result = PinCheck.WRONG_PIN
    if staff.failed_attempts >= MAX_FAILED_ATTEMPTS:
        staff.failed_attempts = 0
        staff.locked_until = now + LOCKOUT
        result = PinCheck.LOCKED
    db.flush()
    return result


def _clean_display_name(display_name: str) -> str:
    name = display_name.strip()
    if not 1 <= len(name) <= DISPLAY_NAME_MAX_LENGTH:
        raise InvalidDisplayNameError(
            f"a name is 1 to {DISPLAY_NAME_MAX_LENGTH} characters"
        )
    return name


def _ensure_name_is_free(db: Session, name: str) -> None:
    # SQL's lower(), not Python's, so this matches the unique index exactly.
    taken = db.scalar(
        select(StaffUser.id).where(
            StaffUser.active,
            func.lower(StaffUser.display_name) == func.lower(name),
        )
    )
    if taken is not None:
        raise DuplicateDisplayNameError("another active staff member has this name")


def _ensure_not_last_manager(db: Session, staff: StaffUser) -> None:
    if not (staff.active and staff.role is Role.MANAGER):
        return
    other_managers = db.scalar(
        select(func.count()).where(
            StaffUser.active,
            StaffUser.role == Role.MANAGER,
            StaffUser.id != staff.id,
        )
    )
    if not other_managers:
        raise LastManagerError("there must be at least one active manager")
