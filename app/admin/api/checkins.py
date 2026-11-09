"""Manual check-in at the desk (design doc: "Manual check-in", "The monthly
choice"; decisions 0004, 0017, 0032).

- ``POST /api/customers/{id}/check-in`` (``checkins.manual``, every role):
  check the customer in as the logged-in staff member. The same order as
  the phone: health form, the 10-minute repeat, a plan for this month.

  - 200 ``checked_in`` or ``already_checked_in``, with the plan covering
    this month.
  - 403 ``plan_not_allowed``: a plan was sent by staff who may not choose
    plans. Instructors send none: with no plan this month, their
    check-in records single entry (decision 0017).
  - 409 ``health_form_required``: show the form's status; nothing else
    can let the customer in (decision 0004).
  - 409 ``plan_required``: the manager picks one of ``options`` and sends
    it.
  - 409 ``price_not_set`` or ``customer_inactive``.

- ``GET /api/customers/{id}/checkins`` (``customers.view``, every role):
  the customer's latest 10 check-ins, newest first, for the customer page.
  Who checked them in at the desk is in the activity log, not here.

The dialog reads what it shows beforehand from ``GET .../health-form`` and
``GET .../plan``; this route only acts.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.admin.api.customers import NOT_FOUND, CanView, CustomerId, customer_or_404
from app.admin.api.health_forms import status_answer
from app.admin.api.schemas import (
    CheckedIn,
    CheckInForbidden,
    CheckInHealthFormRequired,
    CheckInHistory,
    CheckInHistoryEntry,
    CheckInPlanRequired,
    CheckInRefused,
    CheckInRefusedOther,
    CoveringPlan,
    ManualCheckInRequest,
    NotLoggedIn,
    PlanOption,
)
from app.admin.security import StaffLogin, require_permission
from app.core.checkins import (
    HealthFormRequiredError,
    PlanNotAllowedError,
    PlanRequiredError,
    check_in_manually,
    recent_checkins,
)
from app.core.clock import to_local
from app.core.customers import CustomerInactiveError
from app.core.db import DbSession
from app.core.permissions import Permission
from app.core.plans import PriceNotSetError

router = APIRouter(
    prefix="/customers/{customer_id}",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        **NOT_FOUND,
    },
)

CanCheckIn = Annotated[
    StaffLogin, Depends(require_permission(Permission.CHECKINS_MANUAL))
]


@router.get("/checkins")
def history(customer_id: CustomerId, db: DbSession, _login: CanView) -> CheckInHistory:
    customer = customer_or_404(db, customer_id)
    return CheckInHistory(
        checkins=[
            CheckInHistoryEntry(
                id=checkin.id,
                checked_in_at=to_local(checkin.checked_in_at),
                method=checkin.method,
            )
            for checkin in recent_checkins(db, customer)
        ]
    )


@router.post(
    "/check-in",
    response_model=CheckedIn,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": CheckInForbidden},
        status.HTTP_409_CONFLICT: {"model": CheckInRefused},
    },
)
def check_in(
    customer_id: CustomerId,
    body: ManualCheckInRequest,
    db: DbSession,
    login: CanCheckIn,
) -> CheckedIn | JSONResponse:
    customer = customer_or_404(db, customer_id)
    try:
        result = check_in_manually(db, customer, by=login.staff, plan=body.plan)
    except PlanNotAllowedError:
        return JSONResponse(CheckInForbidden().model_dump(), status.HTTP_403_FORBIDDEN)
    except HealthFormRequiredError as refused:
        return _conflict(
            CheckInHealthFormRequired(health_form=status_answer(refused.status))
        )
    except PlanRequiredError as refused:
        return _conflict(
            CheckInPlanRequired(
                month=str(refused.month),
                options=[
                    PlanOption(
                        plan=option.plan,
                        amount_agorot=(
                            None if option.price is None else option.price.amount_agorot
                        ),
                    )
                    for option in refused.options
                ],
            )
        )
    except PriceNotSetError:
        return _conflict(CheckInRefusedOther(error="price_not_set"))
    except CustomerInactiveError:
        return _conflict(CheckInRefusedOther(error="customer_inactive"))

    plan = result.plan
    return CheckedIn(
        outcome=result.outcome,
        checked_in_at=to_local(result.check_in.checked_in_at),
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


def _conflict(
    answer: CheckInHealthFormRequired | CheckInPlanRequired | CheckInRefusedOther,
) -> JSONResponse:
    return JSONResponse(answer.model_dump(mode="json"), status.HTTP_409_CONFLICT)
