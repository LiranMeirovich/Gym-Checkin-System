"""First-run setup as JSON: the gym's name and the first manager account,
on a fresh install (design doc: "First run"; decision 0019).

It exists only while there are no staff accounts at all; afterwards both
routes are a 404, so nobody can use them to make themselves a manager.
No session exists yet, so the only CSRF protection is the same-origin
check (``csrf``), and the host guard keeps DNS-rebinding sites out.

- ``GET /api/setup``: ``{"needed": true}``, or 404 once setup is done.
- ``POST /api/setup``: saves both together or not at all, logs the new
  manager in and answers with the session. On a bad value, 400 with every
  field's problem and nothing saved.
"""

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.admin.api.auth import session_info
from app.admin.api.schemas import (
    SessionInfo,
    SetupField,
    SetupProblem,
    SetupRefused,
    SetupRequest,
    SetupStatus,
)
from app.admin.security import set_session_cookie
from app.core.db import DbSession
from app.core.gym_settings import (
    InvalidSettingsChangeError,
    check_gym_settings,
    update_gym_settings,
)
from app.core.models import StaffUser
from app.core.pins import InvalidPinError, validate_pin
from app.core.staff import (
    DuplicateDisplayNameError,
    InvalidDisplayNameError,
    SetupAlreadyDoneError,
    any_staff_exists,
    create_first_manager,
)
from app.core.staff_sessions import idle_timeout, lock_settings, start_session

router = APIRouter()


class SetupInvalidError(Exception):
    def __init__(self, errors: dict[SetupField, SetupProblem]) -> None:
        self.errors = errors


@router.get("/setup", responses={status.HTTP_404_NOT_FOUND: {}})
def setup_status(db: DbSession) -> SetupStatus:
    _ensure_not_done(db)
    return SetupStatus()


@router.post(
    "/setup",
    response_model=SessionInfo,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": SetupRefused},
        status.HTTP_404_NOT_FOUND: {},
    },
)
def finish_setup(
    body: SetupRequest, response: Response, db: DbSession
) -> SessionInfo | JSONResponse:
    _ensure_not_done(db)
    try:
        # A savepoint: if the second write fails, the first is undone too,
        # and the request can still commit an empty change and answer.
        with db.begin_nested():
            manager = create_manager(
                db, body.gym_name, body.display_name, body.pin, body.pin_again
            )
    except SetupInvalidError as failure:
        refused = SetupRefused(errors=failure.errors)
        return JSONResponse(refused.model_dump(), status.HTTP_400_BAD_REQUEST)
    except SetupAlreadyDoneError:
        # Two setups at once: the other one won.
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    token = start_session(db, manager)
    set_session_cookie(response, token)
    return session_info(manager, token, idle_timeout(lock_settings(db), manager.role))


def create_manager(
    db: DbSession, gym_name: str, display_name: str, pin: str, pin_again: str
) -> StaffUser:
    """Create the first manager and save the gym's name, or raise
    ``SetupInvalidError`` naming every field with a problem."""
    errors: dict[SetupField, SetupProblem] = {}
    try:
        validate_pin(pin)
    except InvalidPinError:
        errors["pin"] = "invalid"
    else:
        if pin != pin_again:
            errors["pin_again"] = "mismatch"
    try:
        check_gym_settings({"gym_name": gym_name})
    except InvalidSettingsChangeError:
        errors["gym_name"] = "invalid"
    try:
        manager = create_first_manager(db, display_name, pin)
    except (InvalidDisplayNameError, DuplicateDisplayNameError):
        # A duplicate can't happen on an empty table; kept so a wrong guess
        # about that shows as a field error, not a crash.
        errors["display_name"] = "invalid"
    except InvalidPinError:
        pass  # already reported above
    if errors:
        raise SetupInvalidError(errors)
    # Saved once the manager exists, who is logged as setting it.
    update_gym_settings(db, {"gym_name": gym_name}, by=manager)
    return manager


def _ensure_not_done(db: DbSession) -> None:
    if any_staff_exists(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
