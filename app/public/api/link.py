"""Linking a phone, signing up on it, and asking who it belongs to
flow"; decision 0028).

- ``POST /api/link``: the customer's phone number and the code from the
  desk. If they match, the phone gets a device session and the
  ``gym_device`` cookie, replacing any login this browser had, and the
  answer is the customer's first name and health form status. Otherwise 400 ``link_refused``.
- ``POST /api/sign-up``: a new customer's name, phone number and date of
  birth (decision 0035). Creates the customer and this phone's device
  session, sets the ``gym_device`` cookie the same way, and answers like
  ``/api/link``. 400 names every invalid field; 409 ``phone_taken`` if
  the number is already a customer's, active or not (they go to the desk).
- ``GET /api/me``: whose phone this is and their health form status
  (so the page knows to show the form), or 401 ``not_linked``. Doesn't
  count as using the phone; a check-in does (``POST /api/check-in``).
"""

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.customers import InvalidCustomerError, PhoneTakenError
from app.core.db import DbSession
from app.core.health_forms import health_form_status, local_today
from app.core.models import Customer
from app.core.phone_links import LinkRefusedError, link_phone, sign_up
from app.public.api.health_form import status_answer
from app.public.api.schemas import (
    LinkRefused,
    LinkRequest,
    Me,
    NotLinked,
    PhoneTaken,
    SignUpRefused,
    SignUpRequest,
)
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


@router.post(
    "/sign-up",
    response_model=Me,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": SignUpRefused},
        status.HTTP_409_CONFLICT: {"model": PhoneTaken},
    },
)
def sign_up_route(
    body: SignUpRequest, request: Request, response: Response, db: DbSession
) -> Me | JSONResponse:
    try:
        signed = sign_up(
            db,
            first_name=body.first_name,
            last_name=body.last_name,
            phone=body.phone,
            date_of_birth=body.date_of_birth,
            user_agent=request.headers.get("user-agent", ""),
            replacing_token=request.cookies.get(DEVICE_COOKIE),
        )
    except InvalidCustomerError as refused:
        answer = SignUpRefused(
            errors={field.value: "invalid" for field in refused.fields}
        )
        return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST)
    except PhoneTakenError:
        # Never which customer: this answer goes to anyone on the internet.
        return JSONResponse(PhoneTaken().model_dump(), status.HTTP_409_CONFLICT)
    set_device_cookie(response, signed.token)
    return _me(db, signed.device.customer)


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
