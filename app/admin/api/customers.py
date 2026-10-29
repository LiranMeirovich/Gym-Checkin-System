"""Customers as JSON: the list, one customer's page, adding, editing, the
date of birth, deactivating and reactivating (design doc: "Users and
roles"; decision 0023).

Every route needs its own named permission, checked on the server whatever
React shows:

- ``GET /api/customers?active=true``: the list (``customers.view``).
- ``GET /api/customers/{id}``: one customer (``customers.view``).
- ``POST /api/customers``: add one (``customers.add``). A phone that
  belongs to an inactive customer brings them back instead (201 either
  way, with ``reactivated``); an active customer's is a 409.
- ``PATCH /api/customers/{id}``: name, phone, notes (``customers.edit``).
- ``PUT /api/customers/{id}/date-of-birth``: manager only
  (``customers.edit_birth_date``), since it sets the under-18 price.
- ``POST /api/customers/{id}/deactivate``: manager only
  (``customers.archive``).
- ``POST /api/customers/{id}/reactivate``: ``customers.add``, the same as
  bringing them back by adding their phone.

A broken field is a 400 naming every such field; nothing is saved.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse

from app.admin.api.schemas import (
    MAX_ID,
    CustomerAdded,
    CustomerConflict,
    CustomerDetails,
    CustomerEdit,
    CustomerList,
    CustomerRefused,
    CustomerSummary,
    DateOfBirthChange,
    NewCustomer,
    NotLoggedIn,
)
from app.admin.security import StaffLogin, require_permission
from app.core.clock import to_local
from app.core.customers import (
    CustomerInactiveError,
    InvalidCustomerError,
    PhoneTakenError,
    add_customer,
    change_date_of_birth,
    deactivate_customer,
    edit_customer,
    list_customers,
    reactivate_customer,
)
from app.core.db import DbSession
from app.core.models import Customer
from app.core.permissions import Permission

router = APIRouter(
    prefix="/customers",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanView = Annotated[StaffLogin, Depends(require_permission(Permission.CUSTOMERS_VIEW))]
CanAdd = Annotated[StaffLogin, Depends(require_permission(Permission.CUSTOMERS_ADD))]
CanEdit = Annotated[StaffLogin, Depends(require_permission(Permission.CUSTOMERS_EDIT))]
CanEditBirthDate = Annotated[
    StaffLogin, Depends(require_permission(Permission.CUSTOMERS_EDIT_BIRTH_DATE))
]
CanArchive = Annotated[
    StaffLogin, Depends(require_permission(Permission.CUSTOMERS_ARCHIVE))
]
CustomerId = Annotated[int, Path(ge=1, le=MAX_ID)]

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {}}
REFUSED = {status.HTTP_400_BAD_REQUEST: {"model": CustomerRefused}}
CONFLICT = {status.HTTP_409_CONFLICT: {"model": CustomerConflict}}


@router.get("")
def customer_list(db: DbSession, _login: CanView, active: bool = True) -> CustomerList:
    return CustomerList(
        customers=[
            CustomerSummary(
                id=c.id,
                first_name=c.first_name,
                last_name=c.last_name,
                phone=c.phone,
                active=c.active,
            )
            for c in list_customers(db, active=active)
        ]
    )


@router.get("/{customer_id}", responses=NOT_FOUND)
def customer_page(
    customer_id: CustomerId, db: DbSession, _login: CanView
) -> CustomerDetails:
    return details(_get(db, customer_id))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CustomerAdded,
    responses={**REFUSED, **CONFLICT},
)
def add(
    body: NewCustomer, db: DbSession, login: CanAdd
) -> CustomerAdded | JSONResponse:
    try:
        added = add_customer(db, **body.model_dump(), by=login.staff)
    except InvalidCustomerError as refused:
        return _refused(refused)
    except PhoneTakenError as taken:
        return _phone_taken(taken)
    return CustomerAdded(
        customer=details(added.customer), reactivated=added.reactivated
    )


@router.patch(
    "/{customer_id}",
    response_model=CustomerDetails,
    responses={**NOT_FOUND, **REFUSED, **CONFLICT},
)
def edit(
    customer_id: CustomerId, body: CustomerEdit, db: DbSession, login: CanEdit
) -> CustomerDetails | JSONResponse:
    customer = _get(db, customer_id)
    try:
        edit_customer(db, customer, **body.model_dump(), by=login.staff)
    except InvalidCustomerError as refused:
        return _refused(refused)
    except PhoneTakenError as taken:
        return _phone_taken(taken)
    except CustomerInactiveError:
        return _inactive()
    return details(customer)


@router.put(
    "/{customer_id}/date-of-birth",
    response_model=CustomerDetails,
    responses={**NOT_FOUND, **REFUSED, **CONFLICT},
)
def set_date_of_birth(
    customer_id: CustomerId,
    body: DateOfBirthChange,
    db: DbSession,
    login: CanEditBirthDate,
) -> CustomerDetails | JSONResponse:
    customer = _get(db, customer_id)
    try:
        change_date_of_birth(db, customer, body.date_of_birth, by=login.staff)
    except InvalidCustomerError as refused:
        return _refused(refused)
    except CustomerInactiveError:
        return _inactive()
    return details(customer)


@router.post("/{customer_id}/deactivate", responses=NOT_FOUND)
def deactivate(
    customer_id: CustomerId, db: DbSession, login: CanArchive
) -> CustomerDetails:
    customer = _get(db, customer_id)
    deactivate_customer(db, customer, by=login.staff)
    return details(customer)


@router.post("/{customer_id}/reactivate", responses=NOT_FOUND)
def reactivate(
    customer_id: CustomerId, db: DbSession, login: CanAdd
) -> CustomerDetails:
    customer = _get(db, customer_id)
    reactivate_customer(db, customer, by=login.staff)
    return details(customer)


def details(customer: Customer) -> CustomerDetails:
    return CustomerDetails(
        id=customer.id,
        first_name=customer.first_name,
        last_name=customer.last_name,
        phone=customer.phone,
        active=customer.active,
        date_of_birth=customer.date_of_birth,
        notes=customer.notes,
        created_at=to_local(customer.created_at),
    )


def _get(db: DbSession, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return customer


# The refusals are answered, not raised: nothing was written, and the
# request's transaction commits an empty change.


def _refused(refused: InvalidCustomerError) -> JSONResponse:
    answer = CustomerRefused(
        errors={field.value: "invalid" for field in refused.fields}
    )
    return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST)


def _phone_taken(taken: PhoneTakenError) -> JSONResponse:
    answer = CustomerConflict(error="phone_taken", customer_id=taken.customer.id)
    return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)


def _inactive() -> JSONResponse:
    answer = CustomerConflict(error="customer_inactive")
    return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
