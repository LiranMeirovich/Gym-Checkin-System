"""The wall QR as JSON, for its printable page (design doc: "The wall QR";
decision 0051).

- ``GET /api/wall-qr``: the fixed check-in address
  (``https://<GYM_PUBLIC_HOSTNAME>/c``) and its QR code. Reading it isn't
  logged.

Owner and managers (``settings.edit``): the page is opened from the
Settings screen. Nothing here is editable; the address comes from the
server's config.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.admin.api.schemas import NotLoggedIn, WallQrAnswer
from app.admin.security import StaffLogin, require_permission
from app.core import wall_qr
from app.core.config import get_settings
from app.core.permissions import Permission

router = APIRouter(
    prefix="/wall-qr",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanEdit = Annotated[StaffLogin, Depends(require_permission(Permission.SETTINGS_EDIT))]


@router.get("")
def wall_qr_code(_login: CanEdit) -> WallQrAnswer:
    url = wall_qr.checkin_url(get_settings())
    return WallQrAnswer(
        url=url, qr_image=wall_qr.qr_image(url) if url is not None else None
    )
