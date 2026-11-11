"""The plan routes of the admin JSON API, on the real admin app: what each
role may do, the answers and error codes, and that refused requests save
nothing. Names and amounts are made up."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.main import app
from app.core import months, pins, punch_cards
from app.core.db import get_engine
from app.core.models import (
    ActivityLogEntry,
    ChosenBy,
    Customer,
    Plan,
    PlanChoice,
    Price,
    PunchCard,
    StaffUser,
)
from app.core.months import Month
from app.core.permissions import Role
from app.core.staff import create_owner, create_staff_user

ORIGIN = "http://127.0.0.1:8000"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PIN = "482913"
MONTHLY = {"plan": "monthly", "month": "2026-11"}


@pytest.fixture(autouse=True)
def fixed_month(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (months, punch_cards):
        monkeypatch.setattr(
            module, "utc_now", lambda: datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
        )


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pins, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture
def client(migrated_db: Path) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    staff = create_owner(db, "מנהלת", PIN)
    db.commit()
    return staff


@pytest.fixture
def instructor(db: Session, manager: StaffUser) -> StaffUser:
    staff = create_staff_user(db, "מדריך", Role.INSTRUCTOR, PIN, by=manager)
    db.commit()
    return staff


@pytest.fixture
def customer(db: Session) -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone="+972501234567",
        date_of_birth=date(1990, 5, 1),
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def prices(db: Session) -> None:
    """Every price, set from before this month."""
    for plan, amount in {
        Plan.MONTHLY: 25000,
        Plan.TRI_MONTHLY: 65000,
        Plan.SINGLE_ENTRY: 4000,
    }.items():
        db.add(
            Price(
                plan=plan,
                amount_agorot=amount,
                valid_from_month=Month(2026, 1),
            )
        )
    db.commit()


class Staff:
    """A logged-in browser: sends the CSRF token on every write."""

    def __init__(self, client: TestClient, member: StaffUser) -> None:
        self.client = client
        answer = client.post(
            "/api/login",
            json={"staff_id": member.id, "pin": PIN},
            headers=SAME_ORIGIN,
        )
        assert answer.status_code == 200
        self.headers = {**SAME_ORIGIN, "X-CSRF-Token": answer.json()["csrf_token"]}

    def get(self, customer_id: int):
        return self.client.get(f"/api/customers/{customer_id}/plan")

    def post(self, customer_id: int, json: object):
        return self.client.post(
            f"/api/customers/{customer_id}/plan", json=json, headers=self.headers
        )

    def correct(self, customer_id: int, json: object):
        return self.client.post(
            f"/api/customers/{customer_id}/plan/corrections",
            json=json,
            headers=self.headers,
        )

    def choose(self, customer_id: int, plan: str = "monthly") -> int:
        """Choose ``plan`` this month; returns the choice's id."""
        answer = self.post(customer_id, {"plan": plan, "month": "2026-11"})
        assert answer.status_code == 201
        return answer.json()["covering"]["id"]


@pytest.fixture
def as_manager(client: TestClient, manager: StaffUser) -> Staff:
    return Staff(client, manager)


@pytest.fixture
def as_instructor(client: TestClient, instructor: StaffUser) -> Staff:
    return Staff(client, instructor)


def choices_in_db(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(PlanChoice))


# Who may do what


def test_not_logged_in_gets_401(client: TestClient, customer: Customer) -> None:
    url = f"/api/customers/{customer.id}/plan"
    assert client.get(url).status_code == 401
    assert client.post(url, json=MONTHLY, headers=SAME_ORIGIN).status_code == 401


def test_an_instructor_can_see_the_plan_status(
    as_instructor: Staff, customer: Customer
) -> None:
    assert as_instructor.get(customer.id).status_code == 200


def test_an_instructor_cant_choose_a_plan(
    as_instructor: Staff, customer: Customer, prices: None, db: Session
) -> None:
    assert as_instructor.post(customer.id, MONTHLY).status_code == 403
    assert choices_in_db(db) == 0


def test_a_choice_needs_the_csrf_token(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    answer = as_manager.client.post(
        f"/api/customers/{customer.id}/plan", json=MONTHLY, headers=SAME_ORIGIN
    )
    assert answer.status_code == 403
    assert choices_in_db(db) == 0


def test_an_unknown_customer_is_404(as_manager: Staff) -> None:
    assert as_manager.get(999).status_code == 404
    assert as_manager.post(999, MONTHLY).status_code == 404


# The answers


def test_nothing_chosen_yet(as_manager: Staff, customer: Customer) -> None:
    answer = as_manager.get(customer.id)

    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "no-store"
    assert answer.json() == {
        "current_month": "2026-11",
        "covering": None,
        "correctable": False,
        "options": [
            {"plan": plan, "amount_agorot": None, "entries": None, "valid_until": None}
            for plan in ("monthly", "tri_monthly", "single_entry")
        ],
        # A check-in also offers the punch card (decision 0042).
        "check_in_options": [
            {"plan": plan, "amount_agorot": None, "entries": None, "valid_until": None}
            for plan in ("monthly", "tri_monthly", "single_entry")
        ]
        # The card says its size and the last day a card bought now counts.
        + [
            {
                "plan": "punch_card",
                "amount_agorot": None,
                "entries": 20,
                "valid_until": "2026-12-31",
            }
        ],
        "history": [],
        "punch_card": None,
        "punch_cards": [],
    }


def test_a_choice_answers_with_the_updated_status(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    answer = as_manager.post(customer.id, {"plan": "tri_monthly", "month": "2026-11"})

    assert answer.status_code == 201
    body = answer.json()
    covering = body["covering"]
    assert {k: v for k, v in covering.items() if k not in {"id", "chosen_at"}} == {
        "plan": "tri_monthly",
        "start_month": "2026-11",
        "end_month": "2027-01",
        "unit_price_agorot": 65000,
        "chosen_by": "staff",
        "staff_name": "מנהלת",
        "replaces_id": None,
        "replaced_by_id": None,
    }
    # The gym's local time, with its offset.
    chosen_at = datetime.fromisoformat(covering["chosen_at"])
    assert chosen_at.utcoffset() in {timedelta(hours=2), timedelta(hours=3)}
    assert body["history"] == [covering]
    assert body["correctable"] is True
    assert [o["amount_agorot"] for o in body["options"]] == [25000, 65000, 4000]


def test_a_choice_is_logged_against_the_acting_manager(
    as_manager: Staff, manager: StaffUser, customer: Customer, prices: None, db: Session
) -> None:
    as_manager.post(customer.id, MONTHLY)

    entry = db.scalar(
        select(ActivityLogEntry).where(ActivityLogEntry.action == "plan.choose")
    )
    assert entry.staff_user_id == manager.id


def test_the_request_cannot_set_the_price(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    answer = as_manager.post(customer.id, {**MONTHLY, "unit_price_agorot": 1})

    assert answer.status_code == 201
    assert answer.json()["covering"]["unit_price_agorot"] == 25000


# Refusals


@pytest.mark.parametrize("month", ["2026-10", "2026-12"])
def test_another_month_is_refused(
    as_manager: Staff, customer: Customer, prices: None, db: Session, month: str
) -> None:
    answer = as_manager.post(customer.id, {**MONTHLY, "month": month})

    assert answer.status_code == 400
    assert answer.json() == {"error": "month_not_choosable"}
    assert choices_in_db(db) == 0


def test_an_unset_price_is_refused(
    as_manager: Staff, customer: Customer, db: Session
) -> None:
    answer = as_manager.post(customer.id, MONTHLY)

    assert answer.status_code == 400
    assert answer.json() == {"error": "price_not_set"}
    assert choices_in_db(db) == 0


def test_a_covered_month_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    first = as_manager.post(customer.id, MONTHLY).json()["covering"]

    answer = as_manager.post(customer.id, {**MONTHLY, "plan": "single_entry"})

    assert answer.status_code == 409
    assert answer.json() == {"error": "month_covered", "choice_id": first["id"]}
    assert choices_in_db(db) == 1


def test_an_inactive_customer_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    customer.active = False
    db.commit()

    answer = as_manager.post(customer.id, MONTHLY)

    assert answer.status_code == 409
    assert answer.json() == {"error": "customer_inactive", "choice_id": None}
    assert choices_in_db(db) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"plan": "weekly", "month": "2026-11"},
        {"plan": "monthly", "month": "2026-13"},
        {"plan": "monthly", "month": "2026-11-01"},
        {"plan": "monthly"},
        {"month": "2026-11"},
    ],
)
def test_a_malformed_request_is_422(
    as_manager: Staff, customer: Customer, prices: None, db: Session, body: object
) -> None:
    assert as_manager.post(customer.id, body).status_code == 422
    assert choices_in_db(db) == 0


# Corrections: who may make them


def test_corrections_need_a_login(
    client: TestClient, customer: Customer, as_manager: Staff, prices: None
) -> None:
    choice = as_manager.choose(customer.id)
    client.cookies.clear()

    answer = client.post(
        f"/api/customers/{customer.id}/plan/corrections",
        json={"replaces_id": choice, "plan": None},
        headers=SAME_ORIGIN,
    )
    assert answer.status_code == 401


@pytest.mark.parametrize("plan", ["single_entry", None])
def test_an_instructor_cant_correct_a_plan(
    as_manager: Staff,
    instructor: StaffUser,
    customer: Customer,
    prices: None,
    db: Session,
    plan: str | None,
) -> None:
    choice = as_manager.choose(customer.id)
    as_instructor = Staff(as_manager.client, instructor)

    answer = as_instructor.correct(customer.id, {"replaces_id": choice, "plan": plan})

    assert answer.status_code == 403
    assert choices_in_db(db) == 1


def test_a_correction_needs_the_csrf_token(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    choice = as_manager.choose(customer.id)

    answer = as_manager.client.post(
        f"/api/customers/{customer.id}/plan/corrections",
        json={"replaces_id": choice, "plan": None},
        headers=SAME_ORIGIN,
    )

    assert answer.status_code == 403
    assert choices_in_db(db) == 1


def test_another_customers_choice_is_404(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    other = Customer(
        first_name="Dan",
        last_name="Cohen",
        phone="+972507654321",
        date_of_birth=date(1985, 1, 1),
    )
    db.add(other)
    db.commit()
    theirs = as_manager.choose(other.id)

    for customer_id, choice_id in ((customer.id, theirs), (customer.id, 999)):
        answer = as_manager.correct(
            customer_id, {"replaces_id": choice_id, "plan": None}
        )
        assert answer.status_code == 404
    assert (
        as_manager.correct(999, {"replaces_id": theirs, "plan": None}).status_code
        == 404
    )
    assert choices_in_db(db) == 1


# Corrections: the answers


def test_a_correction_answers_with_the_updated_status(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    single = as_manager.choose(customer.id, "single_entry")

    answer = as_manager.correct(customer.id, {"replaces_id": single, "plan": "monthly"})

    assert answer.status_code == 201
    body = answer.json()
    covering = body["covering"]
    assert covering["plan"] == "monthly"
    assert covering["unit_price_agorot"] == 25000
    assert covering["replaces_id"] == single
    assert covering["replaced_by_id"] is None
    [new, old] = body["history"]
    assert new == covering
    assert (old["id"], old["plan"], old["replaced_by_id"]) == (
        single,
        "single_entry",
        covering["id"],
    )


def test_clearing_answers_with_a_no_plan_row(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    period = as_manager.choose(customer.id, "tri_monthly")

    answer = as_manager.correct(customer.id, {"replaces_id": period, "plan": None})

    assert answer.status_code == 201
    body = answer.json()
    assert body["covering"] is None
    [cleared, old] = body["history"]
    assert {k: v for k, v in cleared.items() if k not in {"id", "chosen_at"}} == {
        "plan": None,
        "start_month": "2026-11",
        "end_month": "2027-01",
        "unit_price_agorot": None,
        "chosen_by": "staff",
        "staff_name": "מנהלת",
        "replaces_id": period,
        "replaced_by_id": None,
    }
    assert old["replaced_by_id"] == cleared["id"]
    # The month is free again.
    assert as_manager.post(customer.id, MONTHLY).status_code == 201


@pytest.mark.parametrize(
    ("plan", "action"), [("monthly", "plan.correct"), (None, "plan.clear")]
)
def test_a_correction_is_logged_against_the_acting_manager(
    as_manager: Staff,
    manager: StaffUser,
    customer: Customer,
    prices: None,
    db: Session,
    plan: str | None,
    action: str,
) -> None:
    single = as_manager.choose(customer.id, "single_entry")

    as_manager.correct(customer.id, {"replaces_id": single, "plan": plan})

    entry = db.scalar(select(ActivityLogEntry).where(ActivityLogEntry.action == action))
    assert entry.staff_user_id == manager.id


def test_a_correction_cannot_set_the_price(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    single = as_manager.choose(customer.id, "single_entry")

    answer = as_manager.correct(
        customer.id,
        {"replaces_id": single, "plan": "monthly", "unit_price_agorot": 1},
    )

    assert answer.json()["covering"]["unit_price_agorot"] == 25000


# Corrections: refusals


def test_a_replaced_choice_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    single = as_manager.choose(customer.id, "single_entry")
    monthly = as_manager.correct(
        customer.id, {"replaces_id": single, "plan": "monthly"}
    ).json()["covering"]["id"]

    # A page still showing the single-entry choice.
    answer = as_manager.correct(customer.id, {"replaces_id": single, "plan": None})

    assert answer.status_code == 409
    assert answer.json() == {"error": "choice_replaced", "choice_id": monthly}
    assert choices_in_db(db) == 2


def test_a_choice_from_an_earlier_month_is_refused(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    october = PlanChoice(
        customer_id=customer.id,
        plan=Plan.TRI_MONTHLY,
        start_month=Month(2026, 10),
        end_month=Month(2026, 12),
        unit_price_agorot=65000,
        chosen_by=ChosenBy.CUSTOMER,
    )
    db.add(october)
    db.commit()

    for plan in ("monthly", None):
        answer = as_manager.correct(
            customer.id, {"replaces_id": october.id, "plan": plan}
        )
        assert answer.status_code == 400
        assert answer.json() == {"error": "not_correctable"}
    assert choices_in_db(db) == 1
    # The status says so, so the page doesn't offer the change.
    status = as_manager.get(customer.id).json()
    assert status["covering"]["id"] == october.id
    assert status["correctable"] is False


def test_a_no_plan_row_is_not_correctable(
    as_manager: Staff, customer: Customer, prices: None
) -> None:
    monthly = as_manager.choose(customer.id)
    cleared = as_manager.correct(
        customer.id, {"replaces_id": monthly, "plan": None}
    ).json()["history"][0]["id"]

    answer = as_manager.correct(
        customer.id, {"replaces_id": cleared, "plan": "monthly"}
    )

    assert answer.status_code == 400
    assert answer.json() == {"error": "not_correctable"}


def test_no_change_is_refused(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    monthly = as_manager.choose(customer.id)

    answer = as_manager.correct(
        customer.id, {"replaces_id": monthly, "plan": "monthly"}
    )

    assert answer.status_code == 400
    assert answer.json() == {"error": "no_change"}
    assert choices_in_db(db) == 1


def test_an_unset_price_is_refused_for_a_correction(
    as_manager: Staff, customer: Customer, db: Session
) -> None:
    # Only the monthly price is set.
    db.add(
        Price(plan=Plan.MONTHLY, amount_agorot=25000, valid_from_month=Month(2026, 1))
    )
    db.commit()
    monthly = as_manager.choose(customer.id)

    answer = as_manager.correct(
        customer.id, {"replaces_id": monthly, "plan": "single_entry"}
    )

    assert answer.status_code == 400
    assert answer.json() == {"error": "price_not_set"}


def test_running_into_a_covered_month_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    monthly = as_manager.choose(customer.id)
    december = PlanChoice(
        customer_id=customer.id,
        plan=Plan.MONTHLY,
        start_month=Month(2026, 12),
        end_month=Month(2026, 12),
        unit_price_agorot=25000,
        chosen_by=ChosenBy.CUSTOMER,
    )
    db.add(december)
    db.commit()

    answer = as_manager.correct(
        customer.id, {"replaces_id": monthly, "plan": "tri_monthly"}
    )

    assert answer.status_code == 409
    assert answer.json() == {"error": "month_covered", "choice_id": december.id}


def test_an_inactive_customers_plan_is_a_conflict(
    as_manager: Staff, customer: Customer, prices: None, db: Session
) -> None:
    monthly = as_manager.choose(customer.id)
    customer.active = False
    db.commit()

    answer = as_manager.correct(customer.id, {"replaces_id": monthly, "plan": None})

    assert answer.status_code == 409
    assert answer.json() == {"error": "customer_inactive", "choice_id": None}
    assert choices_in_db(db) == 1


@pytest.mark.parametrize(
    "body",
    [
        # Clearing has to be said explicitly.
        {"replaces_id": 1},
        {"plan": "monthly"},
        {"replaces_id": 1, "plan": "weekly"},
        {"replaces_id": 0, "plan": None},
        {"replaces_id": 2**63, "plan": None},
        {"replaces_id": "one", "plan": None},
    ],
)
def test_a_malformed_correction_is_422(
    as_manager: Staff, customer: Customer, prices: None, db: Session, body: object
) -> None:
    as_manager.choose(customer.id)

    assert as_manager.correct(customer.id, body).status_code == 422
    assert choices_in_db(db) == 1


# Punch cards (decision 0042)


def add_card(db: Session, customer: Customer, by: StaffUser | None = None) -> int:
    """A card bought this month, still active."""
    card = PunchCard(
        customer_id=customer.id,
        price_agorot=50000,
        bought_month=Month(2026, 11),
        expires_on=date(2027, 1, 1),
        bought_by=ChosenBy.CUSTOMER if by is None else ChosenBy.STAFF,
        staff_user_id=None if by is None else by.id,
    )
    db.add(card)
    db.commit()
    return card.id


def test_the_status_shows_the_active_card_and_every_card(
    as_instructor: Staff, db: Session, manager: StaffUser, customer: Customer
) -> None:
    card_id = add_card(db, customer, by=manager)

    body = as_instructor.get(customer.id).json()

    row = body["punch_card"]
    assert {k: v for k, v in row.items() if k != "bought_at"} == {
        "id": card_id,
        "price_agorot": 50000,
        "bought_month": "2026-11",
        "expires_on": "2027-01-01",
        "valid_until": "2026-12-31",
        "entries": 20,
        "bought_by": "staff",
        "staff_name": "מנהלת",
        "entries_used": 0,
        "entries_left": 20,
    }
    assert body["punch_cards"] == [row]
    assert body["covering"] is None


def test_the_punch_card_is_not_a_choice(
    as_manager: Staff, db: Session, customer: Customer
) -> None:
    db.add(
        Price(
            plan=Plan.PUNCH_CARD, amount_agorot=50000, valid_from_month=Month(2026, 1)
        )
    )
    db.commit()

    answer = as_manager.post(customer.id, {"plan": "punch_card", "month": "2026-11"})

    assert answer.status_code == 400
    assert answer.json() == {"error": "not_a_choice"}
    assert choices_in_db(db) == 0


def test_no_choice_while_a_card_is_active(
    as_manager: Staff, db: Session, customer: Customer, prices: None
) -> None:
    add_card(db, customer)

    answer = as_manager.post(customer.id, MONTHLY)

    assert answer.status_code == 409
    assert answer.json() == {"error": "punch_card_active", "choice_id": None}
    assert choices_in_db(db) == 0


@pytest.mark.parametrize("plan", ["monthly", None])
def test_no_correction_while_a_card_is_active(
    as_manager: Staff, db: Session, customer: Customer, prices: None, plan: str | None
) -> None:
    single = as_manager.choose(customer.id, "single_entry")
    add_card(db, customer)

    answer = as_manager.correct(customer.id, {"replaces_id": single, "plan": plan})

    assert answer.status_code == 409
    assert answer.json() == {"error": "punch_card_active", "choice_id": None}
    assert choices_in_db(db) == 1


def test_correcting_to_the_punch_card_is_refused(
    as_manager: Staff, db: Session, customer: Customer, prices: None
) -> None:
    monthly = as_manager.choose(customer.id)

    answer = as_manager.correct(
        customer.id, {"replaces_id": monthly, "plan": "punch_card"}
    )

    assert answer.status_code == 400
    assert answer.json() == {"error": "not_a_choice"}
    assert choices_in_db(db) == 1
