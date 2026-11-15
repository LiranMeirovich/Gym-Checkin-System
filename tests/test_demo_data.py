"""The demo data script (app.demo_data): it fills a fresh database through
the core rules, and refuses anything but an empty development database."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import demo_data
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.health_forms import FormState, health_form_status, local_today
from app.core.models import CheckIn, Customer, Plan, StaffUser
from app.core.months import Month
from app.core.reports import calculate


@pytest.fixture
def dev(monkeypatch: pytest.MonkeyPatch, migrated_db: Path) -> Path:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    return migrated_db


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.usefixtures("dev")
def test_last_month_has_a_report_with_every_kind_of_row() -> None:
    demo_data.main()

    with Session(get_engine()) as db:
        report = calculate(db, Month.current().plus(-1))

    rows = {row.first_name: (row.plans, row.payment_agorot) for row in report.rows}
    assert rows == {
        "דנה": ((Plan.MONTHLY,), 25000),
        "עדי": ((Plan.MONTHLY,), 25000),
        "יוסי": ((Plan.TRI_MONTHLY,), 65000),
        "מאיה": ((Plan.SINGLE_ENTRY,), 3 * 4000),
        "אורי": ((Plan.PUNCH_CARD,), 50000),
    }
    assert report.total_agorot == 177000


@pytest.mark.usefixtures("dev")
def test_fills_a_fresh_database_with_every_kind_of_customer() -> None:
    demo_data.main()

    with Session(get_engine()) as db:
        assert count(db, StaffUser) == 3
        assert count(db, Customer) == 12
        # Today's 4, and last month's 11.
        assert count(db, CheckIn) == 15
        customers = db.scalars(select(Customer)).all()
        states = {
            health_form_status(db, c, local_today()).state
            for c in customers
            if c.active
        }
        assert states == {
            FormState.VALID,
            FormState.NEEDS_DOCTOR_NOTE,
            FormState.MISSING,
        }
        assert any(not c.active for c in customers)


@pytest.mark.usefixtures("dev")
def test_refuses_a_database_that_has_data() -> None:
    demo_data.main()

    with pytest.raises(SystemExit, match="already has data"):
        demo_data.main()


@pytest.mark.usefixtures("migrated_db")
def test_refuses_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    # Prod settings that would otherwise load.
    monkeypatch.setenv("GYM_ENVIRONMENT", "prod")
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "checkin.example.com")
    monkeypatch.setenv("GYM_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("GYM_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GYM_SMTP_USER", "gym@example.com")
    monkeypatch.setenv("GYM_SMTP_PASSWORD", "not-a-real-password")
    # migrated_db loaded the settings in dev mode.
    get_settings.cache_clear()

    with pytest.raises(SystemExit, match="development only"):
        demo_data.main()
