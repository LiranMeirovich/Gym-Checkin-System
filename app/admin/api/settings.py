"""The gym settings as JSON, for the manager's Settings screen (design
doc: "Data model"; decisions 0016, 0037).

- ``GET /api/settings``: the current values, and which stored ones are
  broken (they show their default until saved over).
- ``PUT /api/settings``: save the whole form. All or nothing; only the
  settings that really change are written and logged.

Owner and managers (``settings.edit``). The rules live in
``app.core.gym_settings``; a broken field is a 400 naming it, never
repeating the value.
"""

from typing import Annotated, get_args

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.admin.api.schemas import (
    GymSettingsAnswer,
    NotLoggedIn,
    SettingsChange,
    SettingsField,
    SettingsRefused,
)
from app.admin.security import StaffLogin, require_permission
from app.core.db import DbSession
from app.core.gym_settings import (
    InvalidSettingsChangeError,
    load_gym_settings_for_editing,
    update_gym_settings,
)
from app.core.permissions import Permission

router = APIRouter(
    prefix="/settings",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanEdit = Annotated[StaffLogin, Depends(require_permission(Permission.SETTINGS_EDIT))]

_FIELDS: frozenset[str] = frozenset(get_args(SettingsField))


@router.get("")
def current(db: DbSession, _login: CanEdit) -> GymSettingsAnswer:
    return _answer(db)


@router.put(
    "",
    response_model=GymSettingsAnswer,
    responses={status.HTTP_400_BAD_REQUEST: {"model": SettingsRefused}},
)
def save(
    body: SettingsChange, db: DbSession, login: CanEdit
) -> GymSettingsAnswer | JSONResponse:
    try:
        update_gym_settings(db, body.model_dump(), by=login.staff)
    except InvalidSettingsChangeError as error:
        return _refused(error.problems)
    return _answer(db)


def _answer(db: DbSession) -> GymSettingsAnswer:
    settings, problems = load_gym_settings_for_editing(db)
    return GymSettingsAnswer(
        **settings.model_dump(mode="json"),
        # A problem's key is the setting, or "setting.position" for one
        # recipient. A row for a setting the code no longer has can't be
        # repaired from this screen, so it isn't listed.
        problems=sorted({key.split(".")[0] for key in problems} & _FIELDS),
    )


def _refused(problems: dict[str, str]) -> JSONResponse:
    """The 400 for ``problems`` (``InvalidSettingsChangeError.problems``):
    which settings failed, without the core's English messages."""
    errors: dict[str, str] = {}
    bad_recipients: list[int] = []
    for key in problems:
        field, _, position = key.partition(".")
        if field == "report_recipients":
            # The list itself fails only when an address repeats; an item
            # fails when it isn't an address.
            if position.isdigit():
                bad_recipients.append(int(position))
                errors[field] = "invalid"
            else:
                errors.setdefault(field, "duplicate")
        elif field in _FIELDS:
            errors[field] = "invalid"
    answer = SettingsRefused(errors=errors, bad_recipients=sorted(bad_recipients))
    return JSONResponse(
        answer.model_dump(mode="json"), status_code=status.HTTP_400_BAD_REQUEST
    )
