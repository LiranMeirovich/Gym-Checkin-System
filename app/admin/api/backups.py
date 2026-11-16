"""Backups as JSON, for the dashboard's backup card (design doc: "Security
and backups").

- ``GET /api/backups/latest``: when the newest backup was made and whether
  it's overdue. Reading it isn't logged.

Owner and managers (``backups.manage``). Backups are made by the admin
app's scheduled job and restored with ``python -m app.restore_backup`` on
the server; neither is a route.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.admin.api.schemas import BackupStatusAnswer, NotLoggedIn
from app.admin.security import StaffLogin, require_permission
from app.core import backups
from app.core.clock import utc_now
from app.core.permissions import Permission

router = APIRouter(
    prefix="/backups",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanManage = Annotated[
    StaffLogin, Depends(require_permission(Permission.BACKUPS_MANAGE))
]


@router.get("/latest")
def latest_backup(_login: CanManage) -> BackupStatusAnswer:
    current = backups.status(utc_now())
    return BackupStatusAnswer(
        configured=current.configured,
        last_backup_at=current.last_backup_at,
        overdue=current.overdue,
    )
