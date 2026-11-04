"""A customer's linked phones as JSON: the link code, the list and Unlink
(design doc: "Check-in flow"; decision 0028).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``POST /api/customers/{id}/link-code``: a new 6-digit code for the
  customer to type on their phone (``phones.link``). An inactive customer
  is a 409 and gets none.
- ``GET /api/customers/{id}/phones``: the live phones
  (``customers.view``).
- ``POST /api/customers/{id}/phones/{phone_id}/unlink``: revoke one,
  answering with the updated list (``phones.link``). A phone that isn't
  this customer's is a 404; one already unlinked changes nothing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse

from app.admin.api.customers import NOT_FOUND, CustomerId, customer_or_404
from app.admin.api.schemas import (
    MAX_ID,
    CustomerConflict,
    LinkCodeIssued,
    LinkedPhone,
    LinkedPhones,
    NotLoggedIn,
)
from app.admin.security import StaffLogin, require_permission
from app.core import phone_links
from app.core.clock import to_local
from app.core.customers import CustomerInactiveError
from app.core.db import DbSession
from app.core.models import Customer, DeviceSession
from app.core.permissions import Permission

router = APIRouter(
    prefix="/customers/{customer_id}",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
        **NOT_FOUND,
    },
)

CanView = Annotated[StaffLogin, Depends(require_permission(Permission.CUSTOMERS_VIEW))]
CanLink = Annotated[StaffLogin, Depends(require_permission(Permission.PHONES_LINK))]
PhoneId = Annotated[int, Path(ge=1, le=MAX_ID)]


@router.post(
    "/link-code",
    status_code=status.HTTP_201_CREATED,
    response_model=LinkCodeIssued,
    responses={status.HTTP_409_CONFLICT: {"model": CustomerConflict}},
)
def issue_code(
    customer_id: CustomerId, db: DbSession, login: CanLink
) -> LinkCodeIssued | JSONResponse:
    customer = customer_or_404(db, customer_id)
    try:
        issued = phone_links.issue_link_code(db, customer, by=login.staff)
    except CustomerInactiveError:
        answer = CustomerConflict(error="customer_inactive")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    return LinkCodeIssued(code=issued.code, expires_at=to_local(issued.expires_at))


@router.get("/phones")
def phones(customer_id: CustomerId, db: DbSession, _login: CanView) -> LinkedPhones:
    return linked_phones(db, customer_or_404(db, customer_id))


@router.post("/phones/{phone_id}/unlink")
def unlink(
    customer_id: CustomerId, phone_id: PhoneId, db: DbSession, login: CanLink
) -> LinkedPhones:
    customer = customer_or_404(db, customer_id)
    device = db.get(DeviceSession, phone_id)
    if device is None or device.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    phone_links.unlink(db, device, by=login.staff)
    return linked_phones(db, customer)


def linked_phones(db: DbSession, customer: Customer) -> LinkedPhones:
    return LinkedPhones(
        phones=[
            LinkedPhone(
                id=device.id,
                user_agent=device.user_agent,
                linked_at=to_local(device.created_at),
                last_used_at=to_local(device.last_seen_at),
            )
            for device in phone_links.list_devices(db, customer)
        ]
    )
