"""The lock screen, logging in and locking (design doc: "Staff login and
lock screen"; decision 0018).

The admin app opens on the lock screen: tap your name, enter your PIN.
Lock ends the session, so the next person logs in as themselves. The page
also locks itself after the role's idle time without a request
(``staff_sessions.idle_timeout``).

- ``GET /login``: the active staff names; ``?staff=<id>`` shows the PIN
  form for one of them. No JavaScript needed. Showing it ends this
  browser's session, however the browser got here (Back, a typed address,
  the auto-lock timer of another tab): a lock screen that looks locked
  must be locked. The cookie is SameSite=Strict, so another website
  can't send a browser here to log it out.
- ``POST /login``: ``staff_id`` and ``pin``. A right PIN replaces any
  session this browser had and goes to ``/``. A refused one shows the
  lock screen again, and the request **commits**, so the lockout counters
  ``check_pin()`` wrote are kept (decision 0018).
- ``POST /lock``: ends the session (CSRF token required, like every
  logged-in form) and goes back to the lock screen.
- ``GET /``: a placeholder home page until the dashboard (milestone 4).
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app.admin.security import (
    LOGIN_PATH,
    SESSION_COOKIE,
    SETUP_PATH,
    CurrentStaff,
    clear_session_cookie,
    set_session_cookie,
)
from app.admin.templating import staff_page, templates
from app.core.clock import to_local
from app.core.db import DbSession
from app.core.models import StaffUser
from app.core.staff import PinCheck, any_staff_exists, check_pin
from app.core.staff_sessions import end_session, find_session, start_session

router = APIRouter()

WRONG_PIN_ERROR = "קוד שגוי"
LOCKED_ERROR = "יותר מדי ניסיונות שגויים. אפשר לנסות שוב בשעה {until}."
NO_SUCH_STAFF_ERROR = "המשתמש לא נמצא. בחרו שם מהרשימה."


@router.get(LOGIN_PATH, response_class=HTMLResponse)
def lock_screen(request: Request, db: DbSession, staff: str | None = None) -> Response:
    if not any_staff_exists(db):
        return RedirectResponse(SETUP_PATH, status.HTTP_303_SEE_OTHER)
    _end_this_browsers_session(request, db)
    chosen = _active_staff(db, staff)
    error = None if chosen or staff is None else NO_SUCH_STAFF_ERROR
    response = _render(request, db, chosen, error)
    if SESSION_COOKIE in request.cookies:
        clear_session_cookie(response)
    return response


@router.post(LOGIN_PATH, response_class=HTMLResponse)
def log_in(
    request: Request,
    db: DbSession,
    staff_id: Annotated[str, Form()] = "",
    pin: Annotated[str, Form()] = "",
) -> Response:
    chosen = _active_staff(db, staff_id)
    if chosen is None:
        return _render(
            request, db, None, NO_SUCH_STAFF_ERROR, status.HTTP_401_UNAUTHORIZED
        )

    # Never raise from here on a refused PIN: raising rolls back the
    # transaction, and with it the failed-attempt count and the lockout.
    result = check_pin(db, chosen, pin)
    if result is PinCheck.OK:
        # Not written to the activity log, which records changes only:
        # staff_sessions is the login history.
        _end_this_browsers_session(request, db)
        token = start_session(db, chosen)
        response = RedirectResponse("/", status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, token)
        return response
    if result is PinCheck.LOCKED:
        until = to_local(chosen.locked_until).strftime("%H:%M")
        error = LOCKED_ERROR.format(until=until)
    elif result is PinCheck.WRONG_PIN:
        error = WRONG_PIN_ERROR
    else:
        # INACTIVE can't happen (_active_staff filters), but stays generic.
        chosen, error = None, NO_SUCH_STAFF_ERROR
    return _render(request, db, chosen, error, status.HTTP_401_UNAUTHORIZED)


@router.post("/lock")
def lock(login: CurrentStaff, db: DbSession) -> Response:
    end_session(db, login.session)
    response = RedirectResponse(LOGIN_PATH, status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response


@router.get("/", response_class=HTMLResponse)
def home(request: Request, login: CurrentStaff) -> Response:
    """Placeholder until the dashboard (milestone 4)."""
    return staff_page(request, login, "home.html")


def _active_staff(db: DbSession, staff_id: str | None) -> StaffUser | None:
    """The active staff member with this id, or ``None`` for a missing,
    malformed, unknown or deactivated one."""
    if not staff_id or not staff_id.isascii() or not staff_id.isdigit():
        return None
    staff = db.get(StaffUser, int(staff_id))
    return staff if staff is not None and staff.active else None


def _end_this_browsers_session(request: Request, db: DbSession) -> None:
    # The lock screen, or someone logging in on a browser where another
    # staff member is still logged in: that session ends rather than
    # lingering until it times out.
    token = request.cookies.get(SESSION_COOKIE)
    if token and (session := find_session(db, token)) is not None:
        end_session(db, session)


def _render(
    request: Request,
    db: DbSession,
    chosen: StaffUser | None,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    names = db.scalars(
        select(StaffUser).where(StaffUser.active).order_by(StaffUser.display_name)
    ).all()
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"names": names, "chosen": chosen, "error": error},
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
