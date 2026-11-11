"""Plans as JSON: what covers a customer this month, and the manager's
choice (design doc: "Plans, prices and billing"; decision 0017).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/customers/{id}/plan``: this month's plan, the plans on offer
  with this customer's prices, and their history, plus the active punch
  card and every card bought (``customers.view``, so instructors see the
  plan status too).
- ``POST /api/customers/{id}/plan``: choose a plan for the current month,
  answering with the updated status. Manager only (``plans.choose``). A
  wrong month, the punch card (bought only at a check-in) or an unset
  price is a 400; a covered month, an active punch card or an inactive
  customer is a 409. Nothing is saved on either.
- ``POST /api/customers/{id}/plan/corrections``: replace one of the
  customer's choices with another plan, or clear it (``plan: null``),
  answering with the updated status. Manager only (``plans.correct``). A
  choice that isn't this customer's is a 404; the refusals are a 400 or a
  409, and save nothing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.admin.api.customers import NOT_FOUND, CustomerId, customer_or_404
from app.admin.api.schemas import (
    Answer,
    CorrectionConflict,
    CorrectionRefused,
    NotLoggedIn,
    PlanChoiceRequest,
    PlanChoiceRow,
    PlanConflict,
    PlanCorrectionRequest,
    PlanOption,
    PlanRefused,
    PlanStatus,
    PunchCardRow,
)
from app.admin.security import StaffLogin, require_permission
from app.core import plans as core
from app.core.clock import to_local
from app.core.customers import CustomerInactiveError
from app.core.db import DbSession
from app.core.models import Customer, PlanChoice
from app.core.months import Month
from app.core.permissions import Permission
from app.core.punch_cards import CardBalance, active_card, card_history

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
CanCorrect = Annotated[
    StaffLogin, Depends(require_permission(Permission.PLANS_CORRECT))
]


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
    try:
        core.choose_plan(
            db, customer, body.plan, Month.parse(body.month), by=login.staff
        )
    except REFUSABLE as refused:
        return _refusal(refused, PlanRefused, PlanConflict)
    return _status(db, customer)


@router.post(
    "/corrections",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanStatus,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": CorrectionRefused},
        status.HTTP_409_CONFLICT: {"model": CorrectionConflict},
    },
)
def correct(
    customer_id: CustomerId,
    body: PlanCorrectionRequest,
    db: DbSession,
    login: CanCorrect,
) -> PlanStatus | JSONResponse:
    customer = customer_or_404(db, customer_id)
    choice = core.choice_of(db, customer, body.replaces_id)
    if choice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    try:
        core.correct_plan(db, customer, choice, body.plan, by=login.staff)
    except REFUSABLE as refused:
        return _refusal(refused, CorrectionRefused, CorrectionConflict)
    return _status(db, customer)


def _status(db: DbSession, customer: Customer) -> PlanStatus:
    overview = core.plan_overview(db, customer)
    active = active_card(db, customer)
    return PlanStatus(
        current_month=str(overview.current_month),
        covering=(
            None
            if overview.covering is None
            else _row(overview.covering, overview.replaced_by)
        ),
        correctable=overview.correctable,
        options=plan_offers(overview.options),
        check_in_options=plan_offers(core.check_in_options(db, overview.current_month)),
        history=[_row(choice, overview.replaced_by) for choice in overview.history],
        punch_card=None if active is None else _card_row(active),
        punch_cards=[_card_row(card) for card in card_history(db, customer)],
    )


def plan_offers(options: list[core.PlanOption]) -> list[PlanOption]:
    """Plans with their prices, as the API sends them."""
    return [
        PlanOption(
            plan=option.plan,
            amount_agorot=None if option.price is None else option.price.amount_agorot,
        )
        for option in options
    ]


def _card_row(balance: CardBalance) -> PunchCardRow:
    card = balance.card
    return PunchCardRow(
        id=card.id,
        price_agorot=card.price_agorot,
        bought_month=str(card.bought_month),
        expires_on=card.expires_on,
        bought_at=to_local(card.bought_at),
        bought_by=card.bought_by,
        staff_name=None if card.staff is None else card.staff.display_name,
        entries_used=balance.entries_used,
        entries_left=balance.entries_left,
    )


def _row(choice: PlanChoice, replaced_by: dict[int, int]) -> PlanChoiceRow:
    return PlanChoiceRow(
        id=choice.id,
        plan=choice.plan,
        start_month=str(choice.start_month),
        end_month=str(choice.end_month),
        unit_price_agorot=choice.unit_price_agorot,
        chosen_at=to_local(choice.chosen_at),
        chosen_by=choice.chosen_by,
        staff_name=None if choice.staff is None else choice.staff.display_name,
        replaces_id=choice.replaces_id,
        replaced_by_id=replaced_by.get(choice.id),
    )


# Every refusal the plan core raises: its status and error code. A route
# builds its own answer shape from these, so a code it doesn't document
# fails loudly (the shapes' Literal) rather than reaching React unnoticed.
# The refusals are answered, not raised: nothing was written, and the
# request's transaction commits an empty change.
REFUSALS: dict[type[ValueError], tuple[int, str]] = {
    CustomerInactiveError: (status.HTTP_409_CONFLICT, "customer_inactive"),
    core.ChoiceReplacedError: (status.HTTP_409_CONFLICT, "choice_replaced"),
    core.MonthCoveredError: (status.HTTP_409_CONFLICT, "month_covered"),
    core.PunchCardActiveError: (status.HTTP_409_CONFLICT, "punch_card_active"),
    core.MonthNotChoosableError: (status.HTTP_400_BAD_REQUEST, "month_not_choosable"),
    core.NotAChoiceError: (status.HTTP_400_BAD_REQUEST, "not_a_choice"),
    core.NotCorrectableError: (status.HTTP_400_BAD_REQUEST, "not_correctable"),
    core.PriceNotSetError: (status.HTTP_400_BAD_REQUEST, "price_not_set"),
    core.NoChangeError: (status.HTTP_400_BAD_REQUEST, "no_change"),
}
REFUSABLE = tuple(REFUSALS)


def _refusal(
    refused: ValueError,
    refused_shape: type[PlanRefused | CorrectionRefused],
    conflict_shape: type[PlanConflict | CorrectionConflict],
) -> JSONResponse:
    code, error = REFUSALS[type(refused)]
    if code == status.HTTP_409_CONFLICT:
        # The choice in the way: the one covering the month, or the one that
        # already replaced the choice being corrected.
        if isinstance(refused, core.MonthCoveredError):
            choice_id: int | None = refused.choice.id
        elif isinstance(refused, core.ChoiceReplacedError):
            choice_id = refused.replacement.id
        else:
            choice_id = None
        answer: Answer = conflict_shape(error=error, choice_id=choice_id)
    else:
        answer = refused_shape(error=error)
    return JSONResponse(answer.model_dump(), code)
