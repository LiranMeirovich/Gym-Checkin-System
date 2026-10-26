"""First-run setup: the admin app's first screen on a fresh install, where
the gym's name and the first manager account are entered (design doc:
"First run").

It exists only while there are no staff accounts at all. Until then every
other admin page sends the browser here (``security``); afterwards this
page is a 404, so nobody can use it to make themselves a manager. The
manager then adds instructors from the staff screen (milestone 4).

No session exists yet, so the only CSRF protection is the same-origin
check (``csrf``). The host guard keeps other websites out by DNS
rebinding, which matters most here, before anyone has a PIN.
"""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.admin.security import SETUP_PATH, set_session_cookie
from app.admin.templating import templates
from app.core.db import DbSession
from app.core.gym_settings import InvalidSettingsChangeError, update_gym_settings
from app.core.models import StaffUser
from app.core.permissions import Role
from app.core.pins import InvalidPinError, validate_pin
from app.core.staff import (
    DuplicateDisplayNameError,
    InvalidDisplayNameError,
    any_staff_exists,
    create_staff_user,
)
from app.core.staff_sessions import start_session

router = APIRouter()

# Shown next to the field. The core's own messages are English, for logs.
GYM_NAME_ERROR = "שם המכון: 1 עד 100 תווים"
NAME_ERROR = "שם: 1 עד 50 תווים, בלי תווים נסתרים"
PIN_ERROR = "קוד: 6 עד 12 ספרות, לא ספרה אחת חוזרת ולא רצף (כמו 123456)"
PIN_MISMATCH_ERROR = "הקודים אינם זהים"


class _SetupFailed(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors


@router.get(SETUP_PATH, response_class=HTMLResponse)
def setup_page(request: Request, db: DbSession) -> Response:
    _ensure_not_done(db)
    return _render(request)


@router.post(SETUP_PATH, response_class=HTMLResponse)
def finish_setup(
    request: Request,
    db: DbSession,
    gym_name: Annotated[str, Form()] = "",
    display_name: Annotated[str, Form()] = "",
    pin: Annotated[str, Form()] = "",
    pin_again: Annotated[str, Form()] = "",
) -> Response:
    """Save the gym's name and the first manager, log the manager in and
    go to the home page. On a bad value, nothing is saved and the form
    comes back with the error next to the field (the PINs are cleared)."""
    _ensure_not_done(db)
    try:
        # A savepoint: if the second write fails, the first is undone too,
        # and the request can still commit an empty change and show the form.
        with db.begin_nested():
            manager = _create_manager(db, gym_name, display_name, pin, pin_again)
    except _SetupFailed as failure:
        return _render(
            request,
            errors=failure.errors,
            values={"gym_name": gym_name, "display_name": display_name},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    # TODO(activity log): record the first manager's creation and the gym
    # name once the activity log exists (CLAUDE.md follow-ups).
    token = start_session(db, manager)
    response = RedirectResponse("/", status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, token)
    return response


def _create_manager(
    db: DbSession, gym_name: str, display_name: str, pin: str, pin_again: str
) -> StaffUser:
    # Every field is checked, so all the problems show at once.
    errors: dict[str, str] = {}
    try:
        validate_pin(pin)
    except InvalidPinError:
        errors["pin"] = PIN_ERROR
    else:
        if pin != pin_again:
            errors["pin_again"] = PIN_MISMATCH_ERROR
    try:
        update_gym_settings(db, {"gym_name": gym_name})
    except InvalidSettingsChangeError:
        errors["gym_name"] = GYM_NAME_ERROR
    try:
        manager = create_staff_user(db, display_name, Role.MANAGER, pin)
    except (InvalidDisplayNameError, DuplicateDisplayNameError):
        # A duplicate can't happen on an empty table; kept so a wrong guess
        # about that shows as a field error, not a crash.
        errors["display_name"] = NAME_ERROR
    except InvalidPinError:
        pass  # already reported above
    if errors:
        raise _SetupFailed(errors)
    return manager


def _ensure_not_done(db: DbSession) -> None:
    if any_staff_exists(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND)


def _render(
    request: Request,
    errors: dict[str, str] | None = None,
    values: dict[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    return templates.TemplateResponse(
        request,
        "setup.html",
        {"errors": errors or {}, "values": values or {}},
        status_code=status_code,
    )
