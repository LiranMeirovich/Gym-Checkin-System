"""Linking a phone and asking who it belongs to (design doc: "Check-in
flow"; decision 0028).

- ``POST /api/link``: the customer's phone number and the code from the
  desk. If they match, the phone gets a device session and the
  ``gym_device`` cookie, replacing any login this browser had, and the
  answer is the customer's first name. Otherwise 400 ``link_refused``.
- ``GET /api/me``: whose phone this is, or 401 ``not_linked``. Doesn't
  count as using the phone; a check-in does (feature 3).
"""

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.db import DbSession
from app.core.phone_links import LinkRefusedError, link_phone
from app.public.api.schemas import LinkRefused, LinkRequest, Me, NotLinked
from app.public.device import (
    DEVICE_COOKIE,
    clear_device_cookie,
    set_device_cookie,
    this_device,
)

router = APIRouter()


@router.post(
    "/link",
    response_model=Me,
    responses={status.HTTP_400_BAD_REQUEST: {"model": LinkRefused}},
)
def link(
    body: LinkRequest, request: Request, response: Response, db: DbSession
) -> Me | JSONResponse:
    try:
        linked = link_phone(
            db,
            phone=body.phone,
            code=body.code,
            user_agent=request.headers.get("user-agent", ""),
            replacing_token=request.cookies.get(DEVICE_COOKIE),
        )
    except LinkRefusedError:
        return JSONResponse(
            LinkRefused().model_dump(), status_code=status.HTTP_400_BAD_REQUEST
        )
    set_device_cookie(response, linked.token)
    return Me(first_name=linked.device.customer.first_name)


@router.get(
    "/me",
    response_model=Me,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": NotLinked}},
)
def me(request: Request, db: DbSession) -> Me | JSONResponse:
    device = this_device(request, db)
    if device is None:
        refused = JSONResponse(
            NotLinked().model_dump(), status_code=status.HTTP_401_UNAUTHORIZED
        )
        # A dead token is no use to the browser; drop it.
        if DEVICE_COOKIE in request.cookies:
            clear_device_cookie(refused)
        return refused
    return Me(first_name=device.customer.first_name)
