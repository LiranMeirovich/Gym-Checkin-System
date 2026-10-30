"""Prices as JSON: the Prices screen and the manager's price changes (design
doc: "Plans, prices and billing").

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/prices``: the prices in effect this month, upcoming changes and
  the history (``prices.view``).
- ``POST /api/prices``: apply prices from a month on, all or none, and answer
  with the updated overview. Manager only (``prices.edit``). A broken part is
  a 400 naming every such part; nothing is saved.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.admin.api.schemas import (
    NotLoggedIn,
    PriceChanges,
    PriceInEffect,
    PriceOverview,
    PriceRow,
    PricesRefused,
)
from app.admin.security import StaffLogin, require_permission
from app.core import prices as core
from app.core.clock import to_local
from app.core.db import DbSession
from app.core.models import Price
from app.core.months import Month
from app.core.permissions import Permission

router = APIRouter(
    prefix="/prices",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanView = Annotated[StaffLogin, Depends(require_permission(Permission.PRICES_VIEW))]
CanEdit = Annotated[StaffLogin, Depends(require_permission(Permission.PRICES_EDIT))]


@router.get("")
def price_screen(db: DbSession, _login: CanView) -> PriceOverview:
    return _overview(db)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PriceOverview,
    responses={status.HTTP_400_BAD_REQUEST: {"model": PricesRefused}},
)
def change_prices(
    body: PriceChanges, db: DbSession, login: CanEdit
) -> PriceOverview | JSONResponse:
    try:
        core.set_prices(
            db,
            Month.parse(body.valid_from_month),
            [
                core.PriceChange(p.plan, p.age_group, p.amount_agorot)
                for p in body.prices
            ],
            by=login.staff,
        )
    except core.InvalidPricesError as refused:
        # Answered, not raised: nothing was written, and the request's
        # transaction commits an empty change.
        answer = PricesRefused(errors=dict.fromkeys(refused.fields, "invalid"))
        return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST)
    return _overview(db)


def _overview(db: DbSession) -> PriceOverview:
    overview = core.price_overview(db)
    return PriceOverview(
        current_month=str(overview.current_month),
        current=[
            PriceInEffect(
                plan=cell.plan,
                age_group=cell.age_group,
                amount_agorot=None if cell.price is None else cell.price.amount_agorot,
                valid_from_month=(
                    None if cell.price is None else str(cell.price.valid_from_month)
                ),
            )
            for cell in overview.current
        ],
        upcoming=[_row(price) for price in overview.upcoming],
        history=[_row(price) for price in overview.history],
    )


def _row(price: Price) -> PriceRow:
    return PriceRow(
        id=price.id,
        plan=price.plan,
        age_group=price.age_group,
        amount_agorot=price.amount_agorot,
        valid_from_month=str(price.valid_from_month),
        created_at=to_local(price.created_at),
    )
