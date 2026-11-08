"""Linking a customer's phone: issuing codes, linking, finding the device
behind a token, listing and unlinking phones. Names and numbers are made
up."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import phone_links
from app.core.customers import (
    CustomerField,
    CustomerInactiveError,
    InvalidCustomerError,
    PhoneTakenError,
    deactivate_customer,
    reactivate_customer,
)
from app.core.db import get_engine
from app.core.models import (
    ActivityLogEntry,
    Customer,
    DeviceSession,
    LinkCode,
    StaffUser,
)
from app.core.permissions import Role
from app.core.phone_links import (
    CODE_LIFETIME,
    DEVICE_SESSION_LIFETIME,
    LinkRefusedError,
    find_device,
    issue_link_code,
    link_phone,
    list_devices,
    unlink,
)
from app.core.staff_sessions import hash_token

FAKE_PIN_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake"
START = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
PHONE = "050-123 4567"
UA = "Mozilla/5.0 (iPhone)"


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(phone_links, "utc_now", clock)
    return clock


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def staff(db: Session) -> StaffUser:
    member = StaffUser(
        display_name="Dana", role=Role.INSTRUCTOR, pin_hash=FAKE_PIN_HASH
    )
    db.add(member)
    db.flush()
    return member


def make_customer(db: Session, phone: str = "+972501234567") -> Customer:
    customer = Customer(
        first_name="Noa",
        last_name="Levi",
        phone=phone,
        date_of_birth=date(1995, 5, 17),
    )
    db.add(customer)
    db.flush()
    return customer


@pytest.fixture
def customer(db: Session) -> Customer:
    return make_customer(db)


def link(db: Session, code: str, phone: str = PHONE, **kwargs: object):
    return link_phone(db, phone=phone, code=code, user_agent=UA, **kwargs)


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def log_entries(db: Session) -> list[ActivityLogEntry]:
    return list(db.scalars(select(ActivityLogEntry).order_by(ActivityLogEntry.id)))


# Issuing codes


def test_a_code_is_six_digits_and_lasts_fifteen_minutes(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    issued = issue_link_code(db, customer, by=staff)

    assert len(issued.code) == 6 and issued.code.isdigit()
    assert issued.expires_at == START + timedelta(minutes=15) == START + CODE_LIFETIME


def test_only_the_codes_hash_is_stored(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    issued = issue_link_code(db, customer, by=staff)

    row = db.scalars(select(LinkCode)).one()
    assert row.code_hash == hash_token(issued.code)
    assert row.created_by == staff.id
    assert row.used_at is None


def test_issuing_a_code_is_logged_without_the_code(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    issued = issue_link_code(db, customer, by=staff)

    (entry,) = log_entries(db)
    assert entry.action == "phone.issue_code"
    assert (entry.target_type, entry.target_id) == ("customer", customer.id)
    assert entry.staff_user_id == staff.id
    assert json.loads(entry.after_json) == {
        "link_code_id": db.scalars(select(LinkCode.id)).one()
    }
    assert issued.code not in entry.after_json


def test_an_inactive_customer_gets_no_code(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    customer.active = False

    with pytest.raises(CustomerInactiveError):
        issue_link_code(db, customer, by=staff)
    assert db.scalars(select(LinkCode)).all() == []


# Linking


def test_the_right_number_and_code_link_the_phone(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    linked = link(db, code)

    assert linked.device.customer_id == customer.id
    assert linked.device.token_hash == hash_token(linked.token)
    assert linked.device.user_agent == UA
    assert linked.device.created_at == linked.device.last_seen_at == START
    assert db.scalars(select(LinkCode)).one().used_at == START
    assert find_device(db, linked.token) == linked.device


@pytest.mark.parametrize(
    "typed", ["0501234567", "+972501234567", "972-50-123-4567", " 050 1234567 "]
)
def test_any_way_of_typing_the_number_works(
    db: Session, customer: Customer, staff: StaffUser, typed: str
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    assert link(db, code, phone=typed).device.customer_id == customer.id


def test_spaces_around_the_code_are_ignored(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    link(db, f" {code} ")


def test_a_long_user_agent_is_cut(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    device = link_phone(db, phone=PHONE, code=code, user_agent="x" * 500).device

    assert device.user_agent == "x" * 200


def test_linking_is_not_logged(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code
    link(db, code)

    assert [entry.action for entry in log_entries(db)] == ["phone.issue_code"]


def test_a_code_still_works_just_before_it_expires(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    code = issue_link_code(db, customer, by=staff).code
    clock.advance(CODE_LIFETIME - timedelta(seconds=1))

    link(db, code)


def refused(db: Session, code: str, phone: str = PHONE) -> None:
    devices_before = db.scalars(select(DeviceSession)).all()
    with pytest.raises(LinkRefusedError):
        link(db, code, phone=phone)
    assert db.scalars(select(DeviceSession)).all() == devices_before


def test_a_wrong_code_is_refused(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    refused(db, wrong(code))
    # And it didn't use up the code.
    assert db.scalars(select(LinkCode)).one().used_at is None
    link(db, code)


def test_a_code_is_used_once(db: Session, customer: Customer, staff: StaffUser) -> None:
    code = issue_link_code(db, customer, by=staff).code
    link(db, code)

    refused(db, code)


def test_an_expired_code_is_refused(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    code = issue_link_code(db, customer, by=staff).code
    clock.advance(CODE_LIFETIME)

    refused(db, code)


def test_a_new_code_cancels_the_earlier_one(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    first = issue_link_code(db, customer, by=staff).code
    clock.advance(timedelta(minutes=1))
    second = issue_link_code(db, customer, by=staff).code
    if first == second:
        pytest.skip("the two random codes happened to match")

    refused(db, first)
    link(db, second)


def test_another_customers_code_is_refused(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    other = make_customer(db, phone="+972521112233")
    code = issue_link_code(db, other, by=staff).code

    refused(db, code)


def test_a_customer_without_a_code_is_refused(db: Session, customer: Customer) -> None:
    refused(db, "123456")


@pytest.mark.parametrize("phone", ["0549998877", "not a number", ""])
def test_an_unknown_or_invalid_number_is_refused(
    db: Session, customer: Customer, staff: StaffUser, phone: str
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    refused(db, code, phone=phone)


def test_an_inactive_customer_cannot_link(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code
    customer.active = False

    refused(db, code)


# At most 3 phones


def link_new_phone(db: Session, customer: Customer, staff: StaffUser):
    return link(db, issue_link_code(db, customer, by=staff).code)


def test_a_fourth_phone_replaces_the_least_recently_used(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    phones = []
    for _ in range(3):
        phones.append(link_new_phone(db, customer, staff))
        clock.advance(timedelta(days=1))
    # The first phone was used since, so the second is now the least recent.
    phones[0].device.last_seen_at = clock.now
    clock.advance(timedelta(days=1))

    fourth = link_new_phone(db, customer, staff)

    assert phones[1].device.revoked_at == clock.now
    assert find_device(db, phones[1].token) is None
    assert set(list_devices(db, customer)) == {
        phones[0].device,
        phones[2].device,
        fourth.device,
    }


def test_up_to_three_phones_stay_linked(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    phones = [link_new_phone(db, customer, staff) for _ in range(3)]

    assert all(find_device(db, phone.token) for phone in phones)


def test_the_cap_counts_only_live_phones(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    phones = [link_new_phone(db, customer, staff) for _ in range(3)]
    unlink(db, phones[0].device, by=staff)

    link_new_phone(db, customer, staff)

    assert find_device(db, phones[1].token) and find_device(db, phones[2].token)


def test_linking_again_on_the_same_browser_replaces_its_old_login(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    first = link_new_phone(db, customer, staff)

    second = link(
        db, issue_link_code(db, customer, by=staff).code, replacing_token=first.token
    )

    assert first.device.revoked_at is not None
    assert list_devices(db, customer) == [second.device]


def test_a_browser_linked_to_someone_else_is_moved_over(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    other = make_customer(db, phone="+972521112233")
    theirs = link(db, issue_link_code(db, other, by=staff).code, phone="0521112233")

    link(db, issue_link_code(db, customer, by=staff).code, replacing_token=theirs.token)

    assert list_devices(db, other) == []


def test_an_unknown_old_token_is_ignored(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    code = issue_link_code(db, customer, by=staff).code

    unknown = "not-a-token"

    link(db, code, replacing_token=unknown)


def test_a_refused_link_keeps_the_old_login(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    first = link_new_phone(db, customer, staff)

    with pytest.raises(LinkRefusedError):
        link(db, "000000", replacing_token=first.token)

    assert find_device(db, first.token) == first.device


# Finding the device behind a token


def test_an_unknown_token_finds_nothing(db: Session) -> None:
    assert find_device(db, "not-a-token") is None


def test_a_session_unused_for_a_year_is_dead(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    linked = link_new_phone(db, customer, staff)

    clock.advance(DEVICE_SESSION_LIFETIME - timedelta(seconds=1))
    assert find_device(db, linked.token) == linked.device
    clock.advance(timedelta(seconds=1))
    assert find_device(db, linked.token) is None
    assert list_devices(db, customer) == []


def test_a_deactivated_customers_phone_is_not_recognised(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    linked = link_new_phone(db, customer, staff)
    customer.active = False
    db.flush()

    assert find_device(db, linked.token) is None


def test_deactivating_a_customer_unlinks_their_phones(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    linked = link_new_phone(db, customer, staff)

    deactivate_customer(db, customer, by=staff)
    reactivate_customer(db, customer, by=staff)

    # Reactivating doesn't bring the old login back.
    assert find_device(db, linked.token) is None
    assert list_devices(db, customer) == []


def test_deactivating_leaves_other_customers_phones(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    other = make_customer(db, phone="+972521112233")
    linked = link(db, issue_link_code(db, other, by=staff).code, "0521112233")

    deactivate_customer(db, customer, by=staff)

    assert find_device(db, linked.token) is not None


def test_a_found_device_comes_with_its_customer(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    linked = link_new_phone(db, customer, staff)
    db.expunge_all()

    device = find_device(db, linked.token)

    assert device is not None
    assert device.customer.first_name == "Noa"


# Listing and unlinking


def test_phones_are_listed_most_recently_used_first(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    older = link_new_phone(db, customer, staff)
    clock.advance(timedelta(hours=1))
    newer = link_new_phone(db, customer, staff)

    assert list_devices(db, customer) == [newer.device, older.device]
    assert list_devices(db, make_customer(db, phone="+972521112233")) == []


def test_unlinking_revokes_the_phone_and_is_logged(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    linked = link_new_phone(db, customer, staff)
    clock.advance(timedelta(hours=1))

    unlink(db, linked.device, by=staff)

    assert linked.device.revoked_at == clock.now
    assert find_device(db, linked.token) is None
    entry = log_entries(db)[-1]
    assert entry.action == "phone.unlink"
    assert (entry.target_type, entry.target_id) == ("device_session", linked.device.id)
    assert json.loads(entry.after_json) == {
        "customer_id": customer.id,
        "revoked": True,
    }
    assert linked.token not in entry.after_json + entry.before_json


def test_unlinking_twice_changes_nothing(
    db: Session, customer: Customer, staff: StaffUser, clock: Clock
) -> None:
    linked = link_new_phone(db, customer, staff)
    unlink(db, linked.device, by=staff)
    revoked_at = linked.device.revoked_at
    count = len(log_entries(db))
    clock.advance(timedelta(hours=1))

    unlink(db, linked.device, by=staff)

    assert linked.device.revoked_at == revoked_at
    assert len(log_entries(db)) == count


# Signing up on the phone (decision 0035)


def sign_up(db: Session, phone: str = PHONE, **kwargs: object):
    details: dict[str, object] = {
        "first_name": "Yael",
        "last_name": "Mizrahi",
        "phone": phone,
        "date_of_birth": date(2001, 3, 9),
        "user_agent": UA,
    }
    return phone_links.sign_up(db, **(details | kwargs))


def test_signing_up_creates_the_customer_and_links_this_phone(db: Session) -> None:
    signed = sign_up(db)

    customer = signed.device.customer
    assert (customer.first_name, customer.last_name) == ("Yael", "Mizrahi")
    assert customer.phone == "+972501234567"
    assert customer.date_of_birth == date(2001, 3, 9)
    assert customer.notes == ""
    assert customer.active
    assert signed.device.token_hash == hash_token(signed.token)
    assert signed.device.user_agent == UA
    assert find_device(db, signed.token) == signed.device


def test_signing_up_is_not_logged(db: Session) -> None:
    sign_up(db)

    assert log_entries(db) == []


@pytest.mark.parametrize("active", [True, False])
def test_a_number_that_is_already_a_customer_is_refused(
    db: Session, customer: Customer, staff: StaffUser, active: bool
) -> None:
    if not active:
        deactivate_customer(db, customer, by=staff)
    before = log_entries(db)

    with pytest.raises(PhoneTakenError):
        sign_up(db, phone="+972 50-123-4567")

    # Nothing changed: no second customer, the inactive one stays inactive,
    # and no phone was linked.
    assert db.scalars(select(Customer)).all() == [customer]
    assert customer.active is active
    assert db.scalars(select(DeviceSession)).all() == []
    assert log_entries(db) == before


def test_every_invalid_field_is_named(db: Session) -> None:
    with pytest.raises(InvalidCustomerError) as refused:
        sign_up(
            db,
            phone="12345",
            first_name="  ",
            last_name="x" * 51,
            date_of_birth=date(2999, 1, 1),
        )

    assert refused.value.fields == {
        CustomerField.FIRST_NAME,
        CustomerField.LAST_NAME,
        CustomerField.PHONE,
        CustomerField.DATE_OF_BIRTH,
    }
    assert db.scalars(select(Customer)).all() == []


def test_names_are_cleaned_like_at_the_desk(db: Session) -> None:
    customer = sign_up(db, first_name="  Yael   Ruth ").device.customer

    assert customer.first_name == "Yael Ruth"


def test_signing_up_replaces_this_browsers_old_login(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    theirs = link_new_phone(db, customer, staff)

    sign_up(db, phone="0521112233", replacing_token=theirs.token)

    assert list_devices(db, customer) == []


def test_a_refused_sign_up_keeps_the_old_login(
    db: Session, customer: Customer, staff: StaffUser
) -> None:
    theirs = link_new_phone(db, customer, staff)

    with pytest.raises(PhoneTakenError):
        sign_up(db, replacing_token=theirs.token)

    assert find_device(db, theirs.token) == theirs.device
