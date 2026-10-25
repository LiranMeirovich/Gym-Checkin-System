"""Who is making an admin request, and whether they may (design doc: "Staff
login and lock screen"; decision 0018).

Every admin route except the lock screen, first-run setup and ``/health``
declares one of these:

- ``CurrentStaff``: any logged-in staff member.
- ``require_permission(Permission.X)``: a logged-in staff member whose
  role has that permission. Code checks named permissions, never roles.

Both load the staff row fresh on every request, so a role change or a
deactivation applies from the next click. Both count the request as
activity, restarting the idle timeout.

Not logged in: a page load is redirected to the lock screen; an HTMX
request gets ``HX-Redirect`` so the whole page goes there, not just the
fragment. Logged in without the permission: 403.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response

from app.core.db import DbSession
from app.core.models import StaffSession, StaffUser
from app.core.permissions import Permission, has_permission
from app.core.staff_sessions import find_session, touch

# The browser's session token. HttpOnly, SameSite=Strict, no expiry (gone
# when the browser closes); set by the login route.
SESSION_COOKIE = "gym_staff"

LOGIN_PATH = "/login"


@dataclass(frozen=True)
class StaffLogin:
    """The logged-in staff member behind a request."""

    staff: StaffUser
    session: StaffSession
    # The cookie's plain token. Only for deriving this session's CSRF token
    # (step 4); never shown or stored.
    token: str


class NotLoggedInError(Exception):
    """No live session: no cookie, or its session ended, timed out or
    belongs to a deactivated staff member."""


def _current_staff(request: Request, db: DbSession) -> StaffLogin:
    token = request.cookies.get(SESSION_COOKIE)
    session = find_session(db, token) if token else None
    if session is None:
        raise NotLoggedInError
    touch(db, session)
    return StaffLogin(staff=session.staff, session=session, token=token)


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


def install(app: FastAPI) -> None:
    """Register the not-logged-in handling on ``app``."""
    app.add_exception_handler(NotLoggedInError, _send_to_login)


def _send_to_login(request: Request, _error: Exception) -> Response:
    if request.headers.get("HX-Request") == "true":
        response: Response = Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": LOGIN_PATH},
        )
    else:
        response = RedirectResponse(LOGIN_PATH, status.HTTP_303_SEE_OTHER)
    # A dead token is no use to the browser; drop it.
    if SESSION_COOKIE in request.cookies:
        response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="strict")
    return response
