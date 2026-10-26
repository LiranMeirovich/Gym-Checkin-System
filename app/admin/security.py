"""Who is making an admin request, and whether they may (design doc: "Staff
login and lock screen"; decision 0018).

Every admin route except the lock screen, first-run setup and ``/health``
declares one of these:

- ``CurrentStaff``: any logged-in staff member.
- ``require_permission(Permission.X)``: a logged-in staff member whose
  role has that permission. Code checks named permissions, never roles.

Both load the staff row fresh on every request, so a role change or a
deactivation applies from the next click. Both count the request as
activity, restarting the idle timeout. On a POST, PUT, PATCH or DELETE
both also check the session's CSRF token (``app.admin.csrf``), and refuse
the request with 403 without it.

Not logged in: a page load is redirected to the lock screen (or to
first-run setup, while there are no staff accounts yet); an HTMX request
gets ``HX-Redirect`` so the whole page goes there, not just the fragment.
Logged in without the permission: 403.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.admin.csrf import (
    CSRF_FIELD,
    CSRF_HEADER,
    UNSAFE_METHODS,
    csrf_token,
    csrf_token_matches,
)
from app.core.db import DbSession, get_engine
from app.core.models import StaffSession, StaffUser
from app.core.permissions import Permission, has_permission
from app.core.staff import any_staff_exists
from app.core.staff_sessions import find_session, idle_timeout, lock_settings, touch

# The browser's session token. HttpOnly, SameSite=Strict, no expiry (gone
# when the browser closes); set by the login route.
SESSION_COOKIE = "gym_staff"

LOGIN_PATH = "/login"
SETUP_PATH = "/setup"


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

    @property
    def csrf_token(self) -> str:
        """This session's CSRF token, for forms and HTMX headers."""
        return csrf_token(self.token)


class NotLoggedInError(Exception):
    """No live session: no cookie, or its session ended, timed out or
    belongs to a deactivated staff member."""


async def _submitted_csrf_token(request: Request) -> str | None:
    # Async only because reading a form body is. Starlette keeps the parsed
    # form on the request, so the route's own Form() fields still work.
    if request.method not in UNSAFE_METHODS:
        return None
    if header := request.headers.get(CSRF_HEADER):
        return header
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        value = (await request.form()).get(CSRF_FIELD)
        return value if isinstance(value, str) else None
    return None


SubmittedCsrfToken = Annotated[str | None, Depends(_submitted_csrf_token)]


def _current_staff(
    request: Request, db: DbSession, submitted_csrf_token: SubmittedCsrfToken
) -> StaffLogin:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise NotLoggedInError
    settings = lock_settings(db)
    session = find_session(db, token, settings)
    if session is None:
        raise NotLoggedInError
    if request.method in UNSAFE_METHODS and not csrf_token_matches(
        token, submitted_csrf_token
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
    app.add_exception_handler(NotLoggedInError, _send_to_login)


def _send_to_login(request: Request, _error: Exception) -> Response:
    # Runs after the request's own transaction has ended, so it reads in a
    # short one of its own.
    with Session(get_engine()) as db:
        target = LOGIN_PATH if any_staff_exists(db) else SETUP_PATH
    if request.headers.get("HX-Request") == "true":
        response: Response = Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": target},
        )
    else:
        response = RedirectResponse(target, status.HTTP_303_SEE_OTHER)
    # A dead token is no use to the browser; drop it.
    if SESSION_COOKIE in request.cookies:
        clear_session_cookie(response)
    return response
