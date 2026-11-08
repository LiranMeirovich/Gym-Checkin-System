"""The activity log as JSON: what staff changed, for the manager (design
doc: "Activity log"; decisions 0021, 0037).

- ``GET /api/activity-log``: one page, newest first, filtered by staff
  member, local days (``from``/``to``), target type and id; ``before_id``
  asks for the next page. Manager only (``activity_log.view``). Reading the
  log isn't itself logged: it holds no form contents or secrets (decision
  0021 logs only the sensitive reads the design doc names).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.admin.api.schemas import (
    ActivityLogItem,
    ActivityLogPage,
    ActivityLogQuery,
    NotLoggedIn,
    StaffName,
)
from app.admin.security import StaffLogin, require_permission
from app.core.activity_log import list_entries
from app.core.clock import to_local
from app.core.db import DbSession
from app.core.permissions import Permission

router = APIRouter(
    prefix="/activity-log",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanView = Annotated[
    StaffLogin, Depends(require_permission(Permission.ACTIVITY_LOG_VIEW))
]


@router.get("")
def activity_log(
    query: Annotated[ActivityLogQuery, Query()], db: DbSession, _login: CanView
) -> ActivityLogPage:
    page = list_entries(
        db,
        staff_user_id=query.staff_id,
        from_date=query.from_date,
        to_date=query.to_date,
        target_type=query.target_type,
        target_id=query.target_id,
        before_id=query.before_id,
    )
    return ActivityLogPage(
        entries=[
            ActivityLogItem(
                id=e.id,
                at=to_local(e.at),
                staff=StaffName(id=e.staff_user_id, display_name=e.staff_name),
                action=e.action,
                target_type=e.target_type,
                target_id=e.target_id,
                target_name=e.target_name,
                before=e.before,
                after=e.after,
            )
            for e in page.entries
        ],
        next_before_id=page.next_before_id,
    )
