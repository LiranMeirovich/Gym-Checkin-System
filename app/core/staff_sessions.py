"""Staff login sessions on the admin app: starting one, finding the session
behind a cookie, and ending it (design doc: "Staff login and lock screen").

A session is a random token in the browser's cookie; the database keeps
only its SHA-256 hash. A session counts only while all of these hold:

- it hasn't been ended (Lock, or a new login on the same browser),
- its last activity was at most ``lock_screen_minutes`` ago (a gym
  setting, 5 by default),
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
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.gym_settings import load_gym_settings
from app.core.models import StaffSession, StaffUser

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


def find_session(db: Session, token: str) -> StaffSession | None:
    """The live session for a cookie's ``token``, or ``None`` if there is
    none: unknown token, ended, idle too long, too old, or its staff
    member was deactivated.

    Doesn't count as activity; the caller decides whether the request does
    (``touch``). A background refresh, such as a live dashboard polling,
    must not keep a session open forever.
    """
    session = db.scalar(
        select(StaffSession)
        .join(StaffSession.staff)
        .where(
            StaffSession.token_hash == hash_token(token),
            StaffSession.ended_at.is_(None),
            StaffUser.active,
        )
    )
    if session is None:
        return None
    now = utc_now()
    idle_timeout = timedelta(minutes=load_gym_settings(db).lock_screen_minutes)
    if now - session.last_seen_at > idle_timeout:
        return None
    if now - session.created_at > MAX_SESSION_AGE:
        return None
    return session


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
