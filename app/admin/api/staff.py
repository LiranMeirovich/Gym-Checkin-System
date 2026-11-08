"""Staff accounts as JSON (design doc: "Users and roles"; decision 0037).

Manager only (``staff.manage``), checked on the server whatever React shows:

- ``GET /api/staff``: every staff account, active or not. The activity log
  screen's staff filter uses it now; the Staff screen (milestone 4, feature
  2) adds the changes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.admin.api.schemas import NotLoggedIn, StaffList, StaffMember
from app.admin.security import StaffLogin, require_permission
from app.core.db import DbSession
from app.core.permissions import Permission
from app.core.staff import list_staff

router = APIRouter(
    prefix="/staff",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanManage = Annotated[StaffLogin, Depends(require_permission(Permission.STAFF_MANAGE))]


@router.get("")
def staff_list(db: DbSession, _login: CanManage) -> StaffList:
    return StaffList(
        staff=[
            StaffMember(
                id=s.id, display_name=s.display_name, role=s.role, active=s.active
            )
            for s in list_staff(db)
        ]
    )
