"""Who is making an admin request, and whether they may (design doc: "Staff
login and lock screen"; decision 0018).

Every admin API route except the lock screen, login, first-run setup and
``/health`` declares one of these:

- ``CurrentStaff``: any logged-in staff member.
- ``require_permission(Permission.X)``: a logged-in staff member whose
  role has that permission. Code checks named permissions, never roles.

Both load the staff row fresh on every request, so a role change or a
deactivation applies from the next click. Both count the request as
activity, restarting the idle timeout. On a POST, PUT, PATCH or DELETE
both also check the session's CSRF token in the ``X-CSRF-Token`` header
(``app.admin.csrf``), and refuse the request with 403 without it.

Not logged in: 401 with ``NotLoggedIn``, saying whether first-run setup is
still needed; the React app goes to the lock screen or setup. Logged in
without the permission: 403.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.admin.api.schemas import NotLoggedIn
from app.admin.csrf import CSRF_HEADER, UNSAFE_METHODS, csrf_token_matches
from app.core.db import DbSession, get_engine
from app.core.models import StaffSession, StaffUser
from app.core.permissions import Permission, has_permission
from app.core.staff import any_staff_exists
from app.core.staff_sessions import find_session, idle_timeout, lock_settings, touch

# The browser's session token. HttpOnly, SameSite=Strict, no expiry (gone
# when the browser closes); set by the login route.
SESSION_COOKIE = "gym_staff"


@dataclass(frozen=True)
class StaffLogin:
    """The logged-in staff member behind a request."""

    staff: StaffUser
    session: StaffSession
    # The cookie's plain token. Only for deriving this session's CSRF token;
    # never shown or stored.
    token: str
    # This staff member's idle time, for the page's own auto-lock timer.
    lock_after: timedelta


class NotLoggedInError(Exception):
    """No live session: no cookie, or its session ended, timed out or
    belongs to a deactivated staff member."""


def _current_staff(request: Request, db: DbSession) -> StaffLogin:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise NotLoggedInError
    settings = lock_settings(db)
    session = find_session(db, token, settings)
    if session is None:
        raise NotLoggedInError
    if request.method in UNSAFE_METHODS and not csrf_token_matches(
        token, request.headers.get(CSRF_HEADER)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or wrong")
    touch(db, session)
    return StaffLogin(
        staff=session.staff,
        session=session,
        token=token,
        lock_after=idle_timeout(settings, session.staff.role),
    )


CurrentStaff = Annotated[StaffLogin, Depends(_current_staff)]


def require_permission(permission: Permission) -> Callable[..., StaffLogin]:
    """A dependency that lets the request through only if the logged-in
    staff member's role has ``permission``, and returns their login.

    ``login: Annotated[StaffLogin, Depends(require_permission(Permission.PRICES_EDIT))]``
    """
    permission = Permission(permission)

    def check(login: CurrentStaff) -> StaffLogin:
        if not has_permission(login.staff.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN)
        return login

    return check


def set_session_cookie(response: Response, token: str) -> None:
    """Hand the browser a new session's token.

    HttpOnly: page scripts can't read it. SameSite=Strict: the browser
    never sends it on a request started by another site. No expiry: it's
    gone when the browser closes, and the server's timeouts end it sooner.
    Not Secure, because the admin app is plain http on 127.0.0.1; that
    changes if hosting puts the admin app behind HTTPS.
    """
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="strict", path="/"
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="strict", path="/")


def install(app: FastAPI) -> None:
    """Register the not-logged-in handling on ``app``."""
    app.add_exception_handler(NotLoggedInError, _not_logged_in)


def _not_logged_in(request: Request, _error: Exception) -> Response:
    # Runs after the request's own transaction has ended, so it reads in a
    # short one of its own.
    with Session(get_engine()) as db:
        setup_done = any_staff_exists(db)
    # The React app decides where to go.
    response = JSONResponse(
        NotLoggedIn(setup_needed=not setup_done).model_dump(),
        status_code=status.HTTP_401_UNAUTHORIZED,
    )
    # A dead token is no use to the browser; drop it.
    if SESSION_COOKIE in request.cookies:
        clear_session_cookie(response)
    return response
