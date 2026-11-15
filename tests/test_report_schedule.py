"""The monthly report's scheduled job (design doc: "Monthly report"): what
each run does for last month, that it never repeats work, retries failed
emails, leaves the manager's own generations alone, and that the admin app
starts and stops its thread. Names, addresses and amounts are made up."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import email, months, report_delivery, report_generation, report_schedule
from app.core.db import get_engine
from app.core.gym_settings import update_gym_settings
from app.core.models import ActivityLogEntry, Report, StaffUser
from app.core.months import Month
from app.core.permissions import Role
from app.core.report_delivery import Stage, start_approve_and_send, status
from tests.test_report_delivery import (
    FAKE_PIN_HASH,
    MANAGER,
    NOV,
    RECIPIENTS,
    Outbox,
    add_monthly,
)

# The real ones: conftest replaces them for every other test.
REAL_START = report_schedule.start
REAL_STOP = report_schedule.stop

# 00:05 on 1 December 2026 in Israel (UTC+2).
FIRST_OF_DECEMBER = datetime(2026, 11, 30, 22, 5, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock(FIRST_OF_DECEMBER)
    monkeypatch.setattr(months, "utc_now", fake)
    return fake


@pytest.fixture(autouse=True)
def no_claims() -> Iterator[None]:
    yield
    report_delivery._claims.clear()  # noqa: SLF001
    report_generation._claims.clear()  # noqa: SLF001


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(email, "send", box.send)
    return box


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


@pytest.fixture
def manager(db: Session) -> StaffUser:
    member = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash=FAKE_PIN_HASH)
    db.add(member)
    db.commit()
    return member


@pytest.fixture
def addresses(db: Session, manager: StaffUser) -> None:
    set_addresses(db, manager)


def set_addresses(db: Session, manager: StaffUser) -> None:
    db.rollback()
    update_gym_settings(
        db,
        {"manager_email": MANAGER, "report_recipients": RECIPIENTS},
        by=manager,
    )
    db.commit()


@pytest.fixture
def noa(db: Session) -> None:
    add_monthly(db, "Noa")


def now(db: Session, month: Month = NOV) -> report_delivery.DeliveryStatus:
    db.rollback()
    return status(db, month)


def generations(db: Session) -> list[Report]:
    db.rollback()
    return list(db.scalars(select(Report).order_by(Report.id)))


def approve(db: Session, manager: StaffUser) -> None:
    db.rollback()
    report_id = status(db, NOV).report_id
    assert report_id is not None
    job = start_approve_and_send(db, NOV, report_id, by=manager)
    db.commit()
    job()


# --- What a run does ---------------------------------------------------------


@pytest.mark.usefixtures("addresses", "noa")
def test_on_the_1st_last_month_is_generated_and_emailed_to_the_manager(
    db: Session, outbox: Outbox
) -> None:
    report_schedule.run_due()

    (generation,) = generations(db)
    assert generation.month == NOV
    assert generation.staff_user_id is None
    (sent,) = outbox.sent
    assert sent.to == (MANAGER,)
    assert now(db).stage is Stage.EMAILED


@pytest.mark.usefixtures("addresses", "noa")
def test_a_second_run_does_nothing(db: Session, outbox: Outbox) -> None:
    report_schedule.run_due()
    report_schedule.run_due()

    assert len(generations(db)) == 1
    assert len(outbox.sent) == 1


@pytest.mark.usefixtures("addresses", "noa")
def test_the_1st_is_israel_time(db: Session, outbox: Outbox, clock: Clock) -> None:
    # 23:59 on 30 November in Israel: November isn't over.
    clock.now = datetime(2026, 11, 30, 21, 59, tzinfo=UTC)

    report_schedule.run_due()

    assert [g.month for g in generations(db)] == [Month(2026, 10)]


@pytest.mark.usefixtures("addresses", "noa")
def test_a_pc_that_was_off_catches_up_later_in_the_month(
    db: Session, outbox: Outbox, clock: Clock
) -> None:
    clock.now = datetime(2026, 12, 9, 8, 0, tzinfo=UTC)

    report_schedule.run_due()

    assert [g.month for g in generations(db)] == [NOV]
    assert len(outbox.sent) == 1


@pytest.mark.usefixtures("addresses", "noa")
def test_the_jobs_work_isnt_logged(db: Session, outbox: Outbox) -> None:
    report_schedule.run_due()

    db.rollback()
    assert db.scalars(select(ActivityLogEntry.action)).all() == ["settings.update"]


# --- The manager's own generations --------------------------------------------


@pytest.mark.usefixtures("addresses", "noa")
def test_a_month_the_manager_generated_isnt_generated_or_emailed(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    report_generation.generate(NOV, by=manager)

    report_schedule.run_due()

    assert len(generations(db)) == 1
    assert outbox.sent == []


@pytest.mark.usefixtures("addresses", "noa")
def test_a_regeneration_after_the_email_isnt_emailed_again(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    report_schedule.run_due()
    report_generation.generate(NOV, by=manager)

    report_schedule.run_due()

    assert len(generations(db)) == 2
    assert len(outbox.sent) == 1
    assert now(db).stage is Stage.GENERATED


# --- Retries --------------------------------------------------------------------


@pytest.mark.usefixtures("addresses", "noa")
def test_a_failed_manager_email_is_retried_next_run(
    db: Session, outbox: Outbox
) -> None:
    outbox.failing = True
    report_schedule.run_due()
    assert now(db).failed_email is not None

    outbox.failing = False
    report_schedule.run_due()

    assert len(generations(db)) == 1
    assert len(outbox.sent) == 1
    current = now(db)
    assert current.stage is Stage.EMAILED
    assert current.manager_email is not None
    assert current.manager_email.staff_name is None


@pytest.mark.usefixtures("noa")
def test_no_manager_address_waits_until_one_is_set(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    report_schedule.run_due()
    assert outbox.sent == []
    assert now(db).failed_email is not None

    set_addresses(db, manager)
    report_schedule.run_due()

    assert len(outbox.sent) == 1
    assert now(db).stage is Stage.EMAILED


@pytest.mark.usefixtures("addresses", "noa")
def test_a_failed_send_to_the_recipients_is_retried(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    report_schedule.run_due()
    outbox.failing = True
    approve(db, manager)
    assert now(db).stage is Stage.APPROVED

    outbox.failing = False
    report_schedule.run_due()

    assert outbox.sent[-1].to == tuple(RECIPIENTS)
    current = now(db)
    assert current.stage is Stage.SENT
    assert current.recipients_email is not None
    assert current.recipients_email.staff_name is None


@pytest.mark.usefixtures("addresses", "noa")
def test_a_sent_report_is_left_alone(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    report_schedule.run_due()
    approve(db, manager)

    report_schedule.run_due()

    assert len(outbox.sent) == 2


# --- Busy -----------------------------------------------------------------------


@pytest.mark.usefixtures("addresses", "noa")
def test_a_generation_already_running_is_left_to_finish(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    job = report_generation.start(NOV, by=manager)

    report_schedule.run_due()

    job()
    assert len(generations(db)) == 1
    assert outbox.sent == []


@pytest.mark.usefixtures("addresses", "noa")
def test_an_email_going_out_is_left_to_finish(
    db: Session, manager: StaffUser, outbox: Outbox
) -> None:
    report_schedule.run_due()
    db.rollback()
    report_id = status(db, NOV).report_id
    assert report_id is not None
    job = start_approve_and_send(db, NOV, report_id, by=manager)
    db.commit()

    report_schedule.run_due()

    job()
    assert len(outbox.sent) == 2


# --- The thread -------------------------------------------------------------------


def test_the_thread_runs_at_once_and_survives_a_failed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []
    two_runs = threading.Event()

    def run() -> None:
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("first run breaks")
        two_runs.set()

    monkeypatch.setattr(report_schedule, "run_due", run)
    monkeypatch.setattr(report_schedule, "CHECK_EVERY", 0.01)

    REAL_START()
    try:
        assert two_runs.wait(5)
    finally:
        REAL_STOP()

    assert report_schedule._thread is None  # noqa: SLF001


def test_the_admin_app_starts_and_stops_the_job(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.admin.main import app

    calls: list[str] = []
    monkeypatch.setattr(report_schedule, "start", lambda: calls.append("start"))
    monkeypatch.setattr(report_schedule, "stop", lambda: calls.append("stop"))

    with TestClient(app, base_url="http://127.0.0.1:8000"):
        assert calls == ["start"]

    assert calls == ["start", "stop"]


def test_the_public_app_never_starts_the_job(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.public.main import app

    calls: list[str] = []
    monkeypatch.setattr(report_schedule, "start", lambda: calls.append("start"))

    with TestClient(app, base_url="http://127.0.0.1:8001"):
        pass

    assert calls == []
