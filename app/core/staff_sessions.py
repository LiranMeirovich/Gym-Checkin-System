"""Staff login sessions on the admin app: starting one, finding the session
behind a cookie, and ending it (design doc: "Staff login and lock screen").

A session is a random token in the browser's cookie; the database keeps
only its SHA-256 hash. A session counts only while all of these hold:

- it hasn't been ended (Lock, or a new login on the same browser),
- its last activity was at most ``idle_timeout()`` ago: a gym setting per
  role, 5 minutes for managers and 60 for instructors by default,
- it started at most ``MAX_SESSION_AGE`` ago, however active it was,
- its staff member is still active.

Every function works inside the caller's transaction and never commits.
Checking a PIN is not done here: the login route calls
``staff.check_pin()`` first, then ``start_session()``.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from app.core.clock import utc_now
from app.core.gym_settings import GymSettings, load_gym_settings_for_editing
from app.core.models import StaffSession, StaffUser
from app.core.permissions import Role

# A working day. Even a session kept busy all day has to log in again.
MAX_SESSION_AGE = timedelta(hours=12)

# 32 random bytes: far beyond guessing, online or offline.
TOKEN_BYTES = 32


def start_session(db: Session, staff: StaffUser) -> str:
    """Start a session for ``staff``, who has just given the right PIN.

    Returns the plain token for the cookie. It exists only in the return
    value and the browser; it can't be read back from the database.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = utc_now()
    db.add(
        StaffSession(
            staff_user_id=staff.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
        )
    )
    db.flush()
    return token


def find_session(
    db: Session, token: str, settings: GymSettings | None = None
) -> StaffSession | None:
    """The live session for a cookie's ``token``, or ``None`` if there is
    none: unknown token, ended, idle too long, too old, or its staff
    member was deactivated.

    ``settings`` are the lock-time settings to use (``lock_settings``); a
    caller that needs them too passes them in, so they're read once.

    Doesn't count as activity; the caller decides whether the request does
    (``touch``). A background refresh, such as a live dashboard polling,
    must not keep a session open forever.
    """
    session = db.scalar(
        select(StaffSession)
        .join(StaffSession.staff)
        # The staff row comes from the same query, not a second SELECT.
        .options(contains_eager(StaffSession.staff))
        .where(
            StaffSession.token_hash == hash_token(token),
            StaffSession.ended_at.is_(None),
            StaffUser.active,
        )
    )
    if session is None:
        return None
    settings = settings or lock_settings(db)
    now = utc_now()
    if now - session.last_seen_at > idle_timeout(settings, session.staff.role):
        return None
    if now - session.created_at > MAX_SESSION_AGE:
        return None
    return session


def lock_settings(db: Session) -> GymSettings:
    """The gym settings, for the lock times.

    Read with the forgiving loader: a broken settings row (any setting)
    falls back to its default instead of raising. Otherwise one bad row
    would fail every logged-in request, including the settings screen the
    manager needs to repair it (decision 0016).
    """
    settings, _problems = load_gym_settings_for_editing(db)
    return settings


def idle_timeout(settings: GymSettings, role: Role) -> timedelta:
    """How long a session of ``role`` may go without activity. Managers
    lock sooner: they're the ones who can change prices, plans and staff,
    while instructors mostly watch the desk screen."""
    minutes = (
        settings.lock_screen_minutes
        if Role(role) is Role.MANAGER
        else settings.instructor_lock_screen_minutes
    )
    return timedelta(minutes=minutes)


def touch(db: Session, session: StaffSession) -> None:
    """Record activity on ``session``, which restarts its idle timeout."""
    session.last_seen_at = utc_now()
    db.flush()


def end_session(db: Session, session: StaffSession) -> None:
    """End ``session`` (Lock, or a new login replacing it). Ending one that
    has already ended keeps the first end time."""
    if session.ended_at is None:
        session.ended_at = utc_now()
        db.flush()


def hash_token(token: str) -> str:
    """The stored form of a token: its SHA-256 hex digest.

    A plain hash, not Argon2 like PINs: the token is 32 random bytes, so
    there's nothing to brute-force, and it must be found by an exact
    lookup on every request.
    """
    return hashlib.sha256(token.encode()).hexdigest()
