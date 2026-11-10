"""Checking in from the phone (design doc: "Check-in flow", "The monthly
choice"; decisions 0004, 0017, 0025).

- ``POST /api/check-in``: the page the wall QR opens sends this as soon as
  it knows the phone is linked. A ``GET`` never checks anyone in, so a
  link preview or a prefetch can't record a visit.

  - 200 ``checked_in`` or ``already_checked_in`` (within 10 minutes of
    the last check-in), with the plan covering this month.
  - 401 ``not_linked``: show the link form.
  - 409 ``health_form_required``: no form, or it has expired; show the
    form.
  - 409 ``plan_required``: show the plan page with ``options``; the tapped
    plan comes back in ``plan`` and is chosen with the check-in.
  - 409 ``price_not_set``: the tapped plan's price went away meanwhile.

A 200 sets the ``gym_device`` cookie again with the same token, so its
year starts over (design doc: "Login cookie": refreshed on every check-in).
"""

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.checkins import (
    HealthFormRequiredError,
    PlanRequiredError,
    check_in_by_phone,
)
from app.core.customers import CustomerInactiveError
from app.core.db import DbSession
from app.core.plans import PriceNotSetError
from app.public.api.health_form import status_answer
from app.public.api.schemas import (
    CheckedIn,
    CheckInRefused,
    CheckInRequest,
    CoveringPlan,
    HealthFormRequired,
    NotLinked,
    PlanOffer,
    PlanRequired,
    PriceNotSet,
)
from app.public.device import (
    DEVICE_COOKIE,
    refuse_not_linked,
    set_device_cookie,
    this_device,
)

router = APIRouter()


@router.post(
    "/check-in",
    response_model=CheckedIn,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLinked},
        status.HTTP_409_CONFLICT: {"model": CheckInRefused},
    },
)
def check_in(
    body: CheckInRequest, request: Request, response: Response, db: DbSession
) -> CheckedIn | JSONResponse:
    device = this_device(request, db)
    if device is None:
        return refuse_not_linked(request)
    try:
        result = check_in_by_phone(db, device, body.plan)
    except CustomerInactiveError:
        # find_device() already refuses an inactive customer's phone.
        return refuse_not_linked(request)
    except HealthFormRequiredError as refused:
        return _conflict(HealthFormRequired(health_form=status_answer(refused.status)))
    except PlanRequiredError as refused:
        return _conflict(
            PlanRequired(
                month=str(refused.month),
                options=[
                    PlanOffer(
                        plan=option.plan,
                        price_agorot=(
                            None if option.price is None else option.price.amount_agorot
                        ),
                    )
                    for option in refused.options
                ],
            )
        )
    except PriceNotSetError:
        return _conflict(PriceNotSet())

    # this_device() found the session by this very cookie.
    set_device_cookie(response, request.cookies[DEVICE_COOKIE])
    plan = result.plan
    return CheckedIn(
        outcome=result.outcome,
        checked_in_at=result.check_in.checked_in_at,
        plan=(
            None
            if plan is None
            # A covering choice always has a plan: "no plan" rows cover
            # nothing (decision 0026).
            else CoveringPlan(
                plan=plan.plan,
                start_month=str(plan.start_month),
                end_month=str(plan.end_month),
            )
        ),
    )


def _conflict(answer: HealthFormRequired | PlanRequired | PriceNotSet) -> JSONResponse:
    return JSONResponse(answer.model_dump(mode="json"), status.HTTP_409_CONFLICT)
