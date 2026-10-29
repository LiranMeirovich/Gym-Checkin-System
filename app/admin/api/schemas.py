"""Request and response shapes of the admin API. The frontend's TypeScript
types are generated from these (through the OpenAPI spec), so a change
here that breaks the frontend fails its build."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.permissions import Role

# SQLite's integer range. A bigger id can't exist, and SQLite would refuse
# to look it up (a 500), so it's refused as a malformed request instead.
MAX_ID = 2**63 - 1


class NotLoggedIn(BaseModel):
    """401 from any route that needs a login: no session, or it ended or
    timed out. ``setup_needed`` says to go to first-run setup instead of
    the lock screen."""

    detail: Literal["not_logged_in"] = "not_logged_in"
    setup_needed: bool


# ── The lock screen ─────────────────────────────────────────────────────


class StaffName(BaseModel):
    id: int
    display_name: str


class LockScreen(BaseModel):
    """The names to tap; empty with ``setup_needed`` on a fresh install."""

    setup_needed: bool
    staff: list[StaffName]


class LoginRequest(BaseModel):
    staff_id: int = Field(ge=1, le=MAX_ID)
    # Real PINs are 6-12 digits; the cap only keeps a huge value away from
    # the (deliberately slow) PIN check.
    pin: str = Field(max_length=100)


LoginRefusal = Literal["wrong_pin", "locked", "no_such_staff"]


class LoginRefused(BaseModel):
    """401 from ``POST /api/login``. ``locked_until`` (the gym's local
    time, with its offset) comes with ``locked`` only."""

    error: LoginRefusal
    locked_until: datetime | None = None


# ── A logged-in session ─────────────────────────────────────────────────


class StaffInfo(BaseModel):
    id: int
    display_name: str
    role: Role


class SessionInfo(BaseModel):
    """Who is logged in, plus what the page needs to act for them: the
    CSRF token for the ``X-CSRF-Token`` header (kept in memory only) and
    the idle time after which the page goes to the lock screen."""

    staff: StaffInfo
    csrf_token: str
    lock_after_seconds: int


# ── First-run setup ─────────────────────────────────────────────────────


class SetupStatus(BaseModel):
    needed: Literal[True] = True


class SetupRequest(BaseModel):
    gym_name: str
    display_name: str
    pin: str
    pin_again: str


SetupField = Literal["gym_name", "display_name", "pin", "pin_again"]
SetupProblem = Literal["invalid", "mismatch"]


class SetupRefused(BaseModel):
    """400 from ``POST /api/setup``: every field with a problem, at once.
    ``invalid`` breaks that field's rule; ``mismatch`` is ``pin_again``
    differing from ``pin``. Nothing was saved."""

    errors: dict[SetupField, SetupProblem]
