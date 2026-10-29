"""The lock screen, logging in, the current session and locking, as JSON
(design doc: "Staff login and lock screen"; decisions 0018, 0019).

- ``GET /api/lock-screen``: the active staff names. Asking for them ends
  this browser's session, however the page got there (Lock, Back, a typed
  address, another tab's auto-lock timer): a lock screen that looks locked
  must be locked. The cookie is SameSite=Strict, so another website can't
  make a browser do this.
- ``POST /api/login``: a right PIN replaces any session this browser had
  and answers with the new session. A refused one answers 401 with a code,
  and the request **commits**, so the lockout counters ``check_pin()``
  wrote are kept (decision 0018): never raise on a refused PIN.
- ``GET /api/session``: who is logged in, the CSRF token and the lock
  time. Counts as activity, like any logged-in request.
- ``POST /api/lock``: ends the session (CSRF token required).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.admin.api.schemas import (
    LockScreen,
    LoginRefusal,
    LoginRefused,
    LoginRequest,
    NotLoggedIn,
    SessionInfo,
    StaffInfo,
    StaffName,
)
from app.admin.csrf import csrf_token
from app.admin.security import (
    SESSION_COOKIE,
    CurrentStaff,
    clear_session_cookie,
    set_session_cookie,
)
from app.core.clock import to_local
from app.core.db import DbSession
from app.core.models import StaffUser
from app.core.staff import PinCheck, any_staff_exists, check_pin
from app.core.staff_sessions import (
    end_session,
    find_session,
    idle_timeout,
    lock_settings,
    start_session,
)

router = APIRouter()

NOT_LOGGED_IN = {status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn}}


@router.get("/lock-screen")
def lock_screen(request: Request, response: Response, db: DbSession) -> LockScreen:
    if not any_staff_exists(db):
        return LockScreen(setup_needed=True, staff=[])
    end_this_browsers_session(request, db)
    if SESSION_COOKIE in request.cookies:
        clear_session_cookie(response)
    names = db.scalars(
        select(StaffUser).where(StaffUser.active).order_by(StaffUser.display_name)
    )
    return LockScreen(
        setup_needed=False,
        staff=[StaffName(id=s.id, display_name=s.display_name) for s in names],
    )


@router.post(
    "/login",
    response_model=SessionInfo,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": LoginRefused}},
)
def log_in(
    body: LoginRequest, request: Request, response: Response, db: DbSession
) -> SessionInfo | JSONResponse:
    staff = active_staff(db, body.staff_id)
    if staff is None:
        return _refused("no_such_staff")

    result = check_pin(db, staff, body.pin)
    if result is PinCheck.OK:
        # Not written to the activity log, which doesn't record logins:
        # staff_sessions is the login history.
        end_this_browsers_session(request, db)
        token = start_session(db, staff)
        set_session_cookie(response, token)
        return session_info(staff, token, idle_timeout(lock_settings(db), staff.role))
    if result is PinCheck.LOCKED:
        return _refused("locked", locked_until=staff.locked_until)
    if result is PinCheck.WRONG_PIN:
        return _refused("wrong_pin")
    # INACTIVE can't happen (active_staff filters), but stays generic.
    return _refused("no_such_staff")


@router.get("/session", responses=NOT_LOGGED_IN)
def current_session(login: CurrentStaff) -> SessionInfo:
    return session_info(login.staff, login.token, login.lock_after)


@router.post(
    "/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=NOT_LOGGED_IN,
)
def lock(login: CurrentStaff, db: DbSession) -> Response:
    end_session(db, login.session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


def session_info(staff: StaffUser, token: str, lock_after: timedelta) -> SessionInfo:
    """What the page needs for the session whose cookie holds ``token``."""
    return SessionInfo(
        staff=StaffInfo(id=staff.id, display_name=staff.display_name, role=staff.role),
        csrf_token=csrf_token(token),
        lock_after_seconds=int(lock_after.total_seconds()),
    )


def active_staff(db: DbSession, staff_id: int) -> StaffUser | None:
    """The active staff member with this id, or ``None`` for an unknown or
    deactivated one."""
    staff = db.get(StaffUser, staff_id)
    return staff if staff is not None and staff.active else None


def end_this_browsers_session(request: Request, db: DbSession) -> None:
    """End the session this browser's cookie belongs to, if it's live.

    The lock screen, or someone logging in on a browser where another
    staff member is still logged in: that session ends rather than
    lingering until it times out."""
    token = request.cookies.get(SESSION_COOKIE)
    if token and (session := find_session(db, token)) is not None:
        end_session(db, session)


def _refused(
    error: LoginRefusal, *, locked_until: datetime | None = None
) -> JSONResponse:
    body = LoginRefused(
        error=error, locked_until=to_local(locked_until) if locked_until else None
    )
    return JSONResponse(
        body.model_dump(mode="json"), status_code=status.HTTP_401_UNAUTHORIZED
    )
