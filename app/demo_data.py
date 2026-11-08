"""Fill an empty database with made-up data, for showing the system
(decision 0034). Development only: it refuses to run unless
``GYM_ENVIRONMENT=dev`` and the database has no staff yet, so it can never
add to a real gym's data.

Everything goes through the real ``app.core`` functions, in one
transaction, so the data obeys the same rules as data entered on the
screens (and the activity log records it, as the demo manager). Every
name and phone number is invented (decision 0007: the repo is public).

Use a separate database file, never ``gym.db``. From the project root::

    rm -f demo.db
    uv run --env-file .env.demo alembic upgrade head
    uv run --env-file .env.demo python -m app.demo_data

with ``.env.demo`` (git-ignored) holding ``GYM_DATABASE_PATH=demo.db``,
then start the ``admin-demo`` / ``public-demo`` launch configurations
(ports 8010 / 8011).

The demo staff PINs are below. They are test values for this throwaway
database only, printed at the end too.
"""

import io
from datetime import date

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.core.checkins import check_in_manually
from app.core.config import get_settings
from app.core.customers import add_customer, deactivate_customer
from app.core.db import get_engine
from app.core.doctor_notes import add_doctor_note, check_note_image
from app.core.gym_settings import update_gym_settings
from app.core.health_forms import (
    CURRENT_VERSION,
    FORMS,
    Gender,
    check_form,
    local_today,
    save_form,
)
from app.core.models import Customer, Plan, StaffUser
from app.core.months import Month
from app.core.permissions import Role
from app.core.plans import choose_plan
from app.core.prices import PriceChange, set_prices
from app.core.staff import any_staff_exists, create_first_manager, create_staff_user
from app.core.startup import check_database_is_current

GYM_NAME = "מכון הדוגמה"
MANAGER = ("נועה", "246810")
INSTRUCTOR = ("איתי", "135790")

# The form's gender question, given for each demo customer.
FEMALE, MALE = Gender.FEMALE, Gender.MALE

# The design doc's sample prices, in agorot.
PRICES = {Plan.MONTHLY: 25000, Plan.TRI_MONTHLY: 65000, Plan.SINGLE_ENTRY: 4000}


def _signature() -> bytes:
    """A made-up signature: a scribble on a transparent canvas, as the
    signature pad sends it."""
    image = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).line(
        [(40, 170), (110, 60), (160, 150), (230, 70), (300, 160), (420, 90)],
        "black",
        6,
    )
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _doctor_note() -> bytes:
    """A made-up "scan" of a doctor's note: a sheet with lines of text."""
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    for row in range(12):
        draw.line([(80, 140 + row * 70), (820, 140 + row * 70)], "gray", 4)
    draw.line([(500, 1050), (780, 1010)], "black", 6)
    out = io.BytesIO()
    image.save(out, "JPEG")
    return out.getvalue()


def _sign_form(
    db: Session,
    customer: Customer,
    gender: Gender,
    *,
    yes: tuple[str, ...] = (),
    signer: str | None = None,
) -> None:
    """The customer signs today's form on their phone, answering "yes"
    to the questions in ``yes`` and "no" to the rest."""
    form = FORMS[CURRENT_VERSION]
    checked = check_form(
        version=CURRENT_VERSION,
        answers={q.key: q.key in yes for q in form.questions},
        details={},
        gender=gender,
        signer_name=signer or f"{customer.first_name} {customer.last_name}",
        confirmed=True,
        signature_png=_signature(),
    )
    save_form(db, customer, checked, today=local_today())


def _customer(
    db: Session, first: str, last: str, phone: str, born: date, by: StaffUser
) -> Customer:
    return add_customer(
        db,
        first_name=first,
        last_name=last,
        phone=phone,
        date_of_birth=born,
        by=by,
    ).customer


def fill(db: Session) -> None:
    manager = create_first_manager(db, *MANAGER)
    update_gym_settings(db, {"gym_name": GYM_NAME}, by=manager)
    instructor = create_staff_user(
        db, INSTRUCTOR[0], Role.INSTRUCTOR, INSTRUCTOR[1], by=manager
    )

    month = Month.current()
    set_prices(
        db,
        month,
        [PriceChange(plan, amount) for plan, amount in PRICES.items()],
        by=manager,
    )
    first_question = FORMS[CURRENT_VERSION].questions[0].key

    def add(first: str, last: str, phone: str, born: date) -> Customer:
        return _customer(db, first, last, phone, born, manager)

    # Valid form, a plan, in today.
    for first, last, phone, born, gender, plan in [
        ("דנה", "לוי", "050-555-0101", date(1990, 4, 12), FEMALE, Plan.MONTHLY),
        ("יוסי", "כהן", "050-555-0102", date(1985, 9, 3), MALE, Plan.TRI_MONTHLY),
        ("עדי", "פרידמן", "050-555-0103", date(1996, 1, 22), FEMALE, Plan.MONTHLY),
    ]:
        customer = add(first, last, phone, born)
        _sign_form(db, customer, gender)
        choose_plan(db, customer, plan, month, by=manager)
        check_in_manually(db, customer, by=instructor)

    # Valid form, checked in by an instructor with no plan: single entry.
    maya = add("מאיה", "פרץ", "050-555-0104", date(2001, 6, 30))
    _sign_form(db, maya, FEMALE)
    check_in_manually(db, maya, by=instructor)

    # Under 18: the form is signed by a parent.
    eitan = add("איתן", "גולן", "050-555-0105", date(2011, 2, 14))
    _sign_form(db, eitan, MALE, signer="אבי גולן")
    choose_plan(db, eitan, Plan.MONTHLY, month, by=manager)

    # Valid form, no plan yet: the phone's plan page.
    for first, last, phone, born, gender in [
        ("אורי", "מזרחי", "050-555-0106", date(1993, 11, 8), MALE),
        ("ליאור", "שפירא", "050-555-0107", date(1988, 3, 17), FEMALE),
    ]:
        _sign_form(db, add(first, last, phone, born), gender)

    # "Yes" to a question: waiting for a doctor's note.
    noam = add("נועם", "ביטון", "050-555-0108", date(1979, 7, 5))
    _sign_form(db, noam, MALE, yes=(first_question,))

    # "Yes", and the doctor's note is in: the form counts.
    shira = add("שירה", "אברהם", "050-555-0109", date(1982, 12, 1))
    _sign_form(db, shira, FEMALE, yes=(first_question,))
    add_doctor_note(
        db, shira, check_note_image(_doctor_note()), by=manager, today=local_today()
    )
    choose_plan(db, shira, Plan.SINGLE_ENTRY, month, by=manager)

    # No form yet: no check-in until they fill it in.
    add("תמר", "דהן", "050-555-0110", date(1999, 5, 25))
    add("גיל", "רוזן", "050-555-0111", date(1975, 10, 10))

    # A customer who left.
    ronit = add("רונית", "אלון", "050-555-0112", date(1970, 8, 19))
    deactivate_customer(db, ronit, by=manager)


def main() -> None:
    settings = get_settings()
    if settings.environment != "dev":
        raise SystemExit("Demo data is for development only (GYM_ENVIRONMENT=dev).")
    check_database_is_current()
    with Session(get_engine()) as db, db.begin():
        if any_staff_exists(db):
            raise SystemExit(
                f"{settings.database_path} already has data. Demo data goes "
                "into a fresh database only: see this module's docstring."
            )
        fill(db)
    print(f"Demo data added to {settings.database_path}.")
    # Roles, not the Hebrew names: a Windows console may not print them.
    print(f"Manager PIN: {MANAGER[1]}")
    print(f"Instructor PIN: {INSTRUCTOR[1]}")


if __name__ == "__main__":
    main()
