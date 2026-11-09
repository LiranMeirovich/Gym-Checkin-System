"""Staff accounts as JSON (design doc: "Users and roles"; decisions 0018,
0037, 0039).

Owner and managers (``staff.manage``), checked on the server whatever React
shows. Which accounts they may change is ``app.core.staff``'s rule: only
the owner changes managers' accounts (a 403 for a manager), and nobody
demotes or deactivates the owner or resets their PIN for them (a 409
``owner``).

- ``GET /api/staff``: every staff account, active or not, and who is
  locked out after too many wrong PINs.
- ``POST /api/staff``: add one (201).
- ``PUT /api/staff/{id}/pin``: reset their PIN. It lifts a lockout and
  logs them out everywhere, except the manager's own session when they
  reset their own PIN.
- ``PUT /api/staff/{id}/role``: make them a manager or an instructor
  (nobody is made the owner here).
- ``POST /api/staff/{id}/deactivate`` / ``reactivate``.

The changes answer with the changed member. A broken field is a 400; a
rule that refuses the change (a taken name, the owner's account) is a 409.
The rules themselves live in ``app.core.staff``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse

from app.admin.api.schemas import (
    MAX_ID,
    NewStaffMember,
    NotLoggedIn,
    PinReset,
    RoleChange,
    StaffConflict,
    StaffConflictReason,
    StaffField,
    StaffList,
    StaffMember,
    StaffRefused,
)
from app.admin.security import StaffLogin, require_permission
from app.core.clock import to_local
from app.core.db import DbSession
from app.core.models import StaffUser
from app.core.permissions import Permission
from app.core.pins import InvalidPinError
from app.core.staff import (
    DuplicateDisplayNameError,
    InvalidDisplayNameError,
    NeedsOwnerError,
    OwnerAccountError,
    change_role,
    create_staff_user,
    deactivate,
    list_staff,
    locked_until,
    reactivate,
    reset_pin,
)

router = APIRouter(
    prefix="/staff",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanManage = Annotated[StaffLogin, Depends(require_permission(Permission.STAFF_MANAGE))]
StaffId = Annotated[int, Path(ge=1, le=MAX_ID)]

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {}}
# Not refused by require_permission but by the account's rule: a manager
# changing a manager's account. The same answer, a plain 403.
NEEDS_OWNER = HTTPException(status.HTTP_403_FORBIDDEN)
REFUSED = {status.HTTP_400_BAD_REQUEST: {"model": StaffRefused}}
CONFLICT = {status.HTTP_409_CONFLICT: {"model": StaffConflict}}


@router.get("")
def staff_list(db: DbSession, _login: CanManage) -> StaffList:
    return StaffList(staff=[member(s) for s in list_staff(db)])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StaffMember,
    responses={**REFUSED, **CONFLICT},
)
def add(
    body: NewStaffMember, db: DbSession, login: CanManage
) -> StaffMember | JSONResponse:
    try:
        added = create_staff_user(
            db, body.display_name, body.role, body.pin, by=login.staff
        )
    except InvalidDisplayNameError:
        return _refused("display_name")
    except InvalidPinError:
        return _refused("pin")
    except DuplicateDisplayNameError:
        return _conflict("name_taken")
    except NeedsOwnerError:
        raise NEEDS_OWNER from None
    return member(added)


@router.put(
    "/{staff_id}/pin",
    response_model=StaffMember,
    responses={**NOT_FOUND, **REFUSED, **CONFLICT},
)
def new_pin(
    staff_id: StaffId, body: PinReset, db: DbSession, login: CanManage
) -> StaffMember | JSONResponse:
    staff = staff_or_404(db, staff_id)
    try:
        reset_pin(db, staff, body.pin, by=login.staff, keep_session=login.session)
    except InvalidPinError:
        return _refused("pin")
    except OwnerAccountError:
        return _conflict("owner")
    except NeedsOwnerError:
        raise NEEDS_OWNER from None
    return member(staff)


@router.put(
    "/{staff_id}/role",
    response_model=StaffMember,
    responses={**NOT_FOUND, **CONFLICT},
)
def new_role(
    staff_id: StaffId, body: RoleChange, db: DbSession, login: CanManage
) -> StaffMember | JSONResponse:
    staff = staff_or_404(db, staff_id)
    try:
        change_role(db, staff, body.role, by=login.staff)
    except OwnerAccountError:
        return _conflict("owner")
    except NeedsOwnerError:
        raise NEEDS_OWNER from None
    return member(staff)


@router.post(
    "/{staff_id}/deactivate",
    response_model=StaffMember,
    responses={**NOT_FOUND, **CONFLICT},
)
def make_inactive(
    staff_id: StaffId, db: DbSession, login: CanManage
) -> StaffMember | JSONResponse:
    staff = staff_or_404(db, staff_id)
    try:
        deactivate(db, staff, by=login.staff)
    except OwnerAccountError:
        return _conflict("owner")
    except NeedsOwnerError:
        raise NEEDS_OWNER from None
    return member(staff)


@router.post(
    "/{staff_id}/reactivate",
    response_model=StaffMember,
    responses={**NOT_FOUND, **CONFLICT},
)
def make_active(
    staff_id: StaffId, db: DbSession, login: CanManage
) -> StaffMember | JSONResponse:
    staff = staff_or_404(db, staff_id)
    try:
        reactivate(db, staff, by=login.staff)
    except DuplicateDisplayNameError:
        return _conflict("name_taken")
    except NeedsOwnerError:
        raise NEEDS_OWNER from None
    return member(staff)


def member(staff: StaffUser) -> StaffMember:
    until = locked_until(staff)
    return StaffMember(
        id=staff.id,
        display_name=staff.display_name,
        role=staff.role,
        active=staff.active,
        locked_until=to_local(until) if until else None,
    )


def staff_or_404(db: DbSession, staff_id: int) -> StaffUser:
    staff = db.get(StaffUser, staff_id)
    if staff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return staff


# The refusals are answered, not raised: nothing was written, and the
# request's transaction commits an empty change.


def _refused(field: StaffField) -> JSONResponse:
    answer = StaffRefused(errors={field: "invalid"})
    return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST)


def _conflict(error: StaffConflictReason) -> JSONResponse:
    answer = StaffConflict(error=error)
    return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
