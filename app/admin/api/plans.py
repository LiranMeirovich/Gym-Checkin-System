"""Plans as JSON: what covers a customer this month, and the manager's
choice (design doc: "Plans, prices and billing"; decision 0017).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/customers/{id}/plan``: this month's plan, the plans on offer
  with this customer's prices, and their history (``customers.view``, so
  instructors see the plan status too).
- ``POST /api/customers/{id}/plan``: choose a plan for the current month,
  answering with the updated status. Manager only (``plans.choose``). A
  wrong month or an unset price is a 400; a covered month or an inactive
  customer is a 409. Nothing is saved on either.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.admin.api.customers import NOT_FOUND, CustomerId, customer_or_404
from app.admin.api.schemas import (
    NotLoggedIn,
    PlanChoiceRequest,
    PlanChoiceRow,
    PlanConflict,
    PlanOption,
    PlanRefused,
    PlanStatus,
)
from app.admin.security import StaffLogin, require_permission
from app.core import plans as core
from app.core.clock import to_local
from app.core.customers import CustomerInactiveError
from app.core.db import DbSession
from app.core.models import Customer, PlanChoice
from app.core.months import Month
from app.core.permissions import Permission

router = APIRouter(
    prefix="/customers/{customer_id}/plan",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
        **NOT_FOUND,
    },
)

CanView = Annotated[StaffLogin, Depends(require_permission(Permission.CUSTOMERS_VIEW))]
CanChoose = Annotated[StaffLogin, Depends(require_permission(Permission.PLANS_CHOOSE))]


@router.get("")
def plan_status(customer_id: CustomerId, db: DbSession, _login: CanView) -> PlanStatus:
    return _status(db, customer_or_404(db, customer_id))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanStatus,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": PlanRefused},
        status.HTTP_409_CONFLICT: {"model": PlanConflict},
    },
)
def choose(
    customer_id: CustomerId, body: PlanChoiceRequest, db: DbSession, login: CanChoose
) -> PlanStatus | JSONResponse:
    customer = customer_or_404(db, customer_id)
    # The refusals are answered, not raised: nothing was written, and the
    # request's transaction commits an empty change.
    try:
        core.choose_plan(
            db, customer, body.plan, Month.parse(body.month), by=login.staff
        )
    except CustomerInactiveError:
        return _answer(
            PlanConflict(error="customer_inactive"), status.HTTP_409_CONFLICT
        )
    except core.MonthNotChoosableError:
        return _answer(
            PlanRefused(error="month_not_choosable"), status.HTTP_400_BAD_REQUEST
        )
    except core.MonthCoveredError as covered:
        answer = PlanConflict(error="month_covered", choice_id=covered.choice.id)
        return _answer(answer, status.HTTP_409_CONFLICT)
    except core.PriceNotSetError:
        return _answer(PlanRefused(error="price_not_set"), status.HTTP_400_BAD_REQUEST)
    return _status(db, customer)


def _status(db: DbSession, customer: Customer) -> PlanStatus:
    overview = core.plan_overview(db, customer)
    return PlanStatus(
        current_month=str(overview.current_month),
        covering=None if overview.covering is None else _row(overview.covering),
        options=[
            PlanOption(
                plan=option.plan,
                age_group=option.age_group,
                amount_agorot=(
                    None if option.price is None else option.price.amount_agorot
                ),
            )
            for option in overview.options
        ],
        history=[_row(choice) for choice in overview.history],
    )


def _row(choice: PlanChoice) -> PlanChoiceRow:
    return PlanChoiceRow(
        id=choice.id,
        plan=choice.plan,
        start_month=str(choice.start_month),
        end_month=str(choice.end_month),
        age_group=choice.age_group,
        unit_price_agorot=choice.unit_price_agorot,
        chosen_at=to_local(choice.chosen_at),
        chosen_by=choice.chosen_by,
        staff_name=None if choice.staff is None else choice.staff.display_name,
        replaces_id=choice.replaces_id,
    )


def _answer(answer: PlanRefused | PlanConflict, code: int) -> JSONResponse:
    return JSONResponse(answer.model_dump(), code)
