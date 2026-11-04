"""Linking a phone and asking who it belongs to (design doc: "Check-in
flow"; decision 0028).

- ``POST /api/link``: the customer's phone number and the code from the
  desk. If they match, the phone gets a device session and the
  ``gym_device`` cookie, replacing any login this browser had, and the
  answer is the customer's first name and health form status. Otherwise 400 ``link_refused``.
- ``GET /api/me``: whose phone this is and their health form status
  (so the page knows to show the form), or 401 ``not_linked``. Doesn't
  count as using the phone; a check-in does (feature 3).
"""

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import DbSession
from app.core.health_forms import health_form_status, local_today
from app.core.models import Customer
from app.core.phone_links import LinkRefusedError, link_phone
from app.public.api.health_form import status_answer
from app.public.api.schemas import LinkRefused, LinkRequest, Me, NotLinked
from app.public.device import (
    DEVICE_COOKIE,
    refuse_not_linked,
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
    return _me(db, linked.device.customer)


@router.get(
    "/me",
    response_model=Me,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": NotLinked}},
)
def me(request: Request, db: DbSession) -> Me | JSONResponse:
    device = this_device(request, db)
    if device is None:
        return refuse_not_linked(request)
    return _me(db, device.customer)


def _me(db: Session, customer: Customer) -> Me:
    found = health_form_status(db, customer, local_today())
    return Me(first_name=customer.first_name, health_form=status_answer(found))
