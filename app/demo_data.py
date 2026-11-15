"""Fill an empty database with made-up data, for showing the system
(decision 0034). Development only: it refuses to run unless
``GYM_ENVIRONMENT=dev`` and the database has no staff yet, so it can never
add to a real gym's data.

This month's data goes through the real ``app.core`` functions, in one
transaction, so it obeys the same rules as data entered on the screens
(and the activity log records it, as the demo owner). Last month's
(``_last_month()``: the prices, plans, a punch card and check-ins, so the
Reports screen has a finished month to show) can't: the core functions
only take the current month. Those rows are written directly, with their
dates in last month and prices copied as the core would; the database's
own checks and triggers still apply, but they aren't in the activity log.
Every name and phone number is invented (decision 0007: the repo is
public).

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
from datetime import UTC, date, datetime

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
from app.core.models import (
    CheckIn,
    CheckInMethod,
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
from app.core.plans import choose_plan
from app.core.punch_cards import expiry_for
from app.core.staff import any_staff_exists, create_owner, create_staff_user
from app.core.startup import check_database_is_current

GYM_NAME = "מכון הדוגמה"
OWNER = ("נועה", "246810")
# A manager helping the owner (decision 0039): manages instructors only.
MANAGER = ("רון", "570318")
INSTRUCTOR = ("איתי", "135790")

# The form's gender question, given for each demo customer.
FEMALE, MALE = Gender.FEMALE, Gender.MALE

# The design doc's sample prices, in agorot, and a punch card's.
PRICES = {
    Plan.MONTHLY: 25000,
    Plan.TRI_MONTHLY: 65000,
    Plan.SINGLE_ENTRY: 4000,
    Plan.PUNCH_CARD: 50000,
}


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


def _evening(month: Month, day: int) -> datetime:
    """18:00 in the gym's time on ``day`` of ``month``, in UTC."""
    local = datetime(month.year, month.month, day, 18, tzinfo=get_settings().tz)
    return local.astimezone(UTC)


def _last_month(
    db: Session,
    month: Month,
    *,
    monthly: list[Customer],
    tri_monthly: Customer,
    single_entry: Customer,
    card_holder: Customer,
    owner: StaffUser,
    instructor: StaffUser,
) -> None:
    """Last month, written directly (see the module docstring): the prices
    from then on, the plans and a punch card, and check-ins on them. Its
    report: two monthly, a tri-monthly's first month, three single
    entries and the card."""
    last = month.plus(-1)

    def visit(customer: Customer, day: int, card: PunchCard | None = None) -> None:
        db.add(
            CheckIn(
                customer_id=customer.id,
                checked_in_at=_evening(last, day),
                method=CheckInMethod.MANUAL,
                staff_user_id=instructor.id,
                punch_card_id=None if card is None else card.id,
            )
        )

    for plan, amount in PRICES.items():
        db.add(
            Price(
                plan=plan,
                amount_agorot=amount,
                valid_from_month=last,
                created_at=_evening(last, 1),
            )
        )
    for customer, plan, end in [
        *[(c, Plan.MONTHLY, last) for c in monthly],
        (tri_monthly, Plan.TRI_MONTHLY, last.plus(2)),
        (single_entry, Plan.SINGLE_ENTRY, last),
    ]:
        db.add(
            PlanChoice(
                customer_id=customer.id,
                plan=plan,
                start_month=last,
                end_month=end,
                unit_price_agorot=PRICES[plan],
                chosen_at=_evening(last, 2),
                chosen_by=ChosenBy.STAFF,
                staff_user_id=owner.id,
            )
        )
    card = PunchCard(
        customer_id=card_holder.id,
        price_agorot=PRICES[Plan.PUNCH_CARD],
        bought_month=last,
        expires_on=expiry_for(last),
        bought_at=_evening(last, 3),
        bought_by=ChosenBy.CUSTOMER,
    )
    db.add(card)
    db.flush()

    for customer in [*monthly, tri_monthly]:
        visit(customer, 6)
    for day in (5, 12, 19):
        visit(single_entry, day)
    for day in (3, 8, 15, 22, 27):
        visit(card_holder, day, card)
    db.flush()


def fill(db: Session) -> None:
    owner = create_owner(db, *OWNER)
    update_gym_settings(db, {"gym_name": GYM_NAME}, by=owner)
    create_staff_user(db, MANAGER[0], Role.MANAGER, MANAGER[1], by=owner)
    instructor = create_staff_user(
        db, INSTRUCTOR[0], Role.INSTRUCTOR, INSTRUCTOR[1], by=owner
    )

    month = Month.current()
    first_question = FORMS[CURRENT_VERSION].questions[0].key

    def add(first: str, last: str, phone: str, born: date) -> Customer:
        return _customer(db, first, last, phone, born, owner)

    dana = add("דנה", "לוי", "050-555-0101", date(1990, 4, 12))
    yossi = add("יוסי", "כהן", "050-555-0102", date(1985, 9, 3))
    adi = add("עדי", "פרידמן", "050-555-0103", date(1996, 1, 22))
    maya = add("מאיה", "פרץ", "050-555-0104", date(2001, 6, 30))
    uri = add("אורי", "מזרחי", "050-555-0106", date(1993, 11, 8))
    # Last month: monthly for Dana and Adi, a tri-monthly for Yossi that
    # still covers this month, single entries for Maya, a card for Uri.
    _last_month(
        db,
        month,
        monthly=[dana, adi],
        tri_monthly=yossi,
        single_entry=maya,
        card_holder=uri,
        owner=owner,
        instructor=instructor,
    )

    # Valid form, a plan, in today (Yossi's tri-monthly from last month).
    for customer, gender, plan in [
        (dana, FEMALE, Plan.MONTHLY),
        (yossi, MALE, None),
        (adi, FEMALE, Plan.MONTHLY),
    ]:
        _sign_form(db, customer, gender)
        if plan is not None:
            choose_plan(db, customer, plan, month, by=owner)
        check_in_manually(db, customer, by=instructor)

    # Valid form, checked in by an instructor with no plan: single entry.
    _sign_form(db, maya, FEMALE)
    check_in_manually(db, maya, by=instructor)

    # Under 18: the form is signed by a parent.
    eitan = add("איתן", "גולן", "050-555-0105", date(2011, 2, 14))
    _sign_form(db, eitan, MALE, signer="אבי גולן")
    choose_plan(db, eitan, Plan.MONTHLY, month, by=owner)

    # Valid form, a punch card from last month with entries left.
    _sign_form(db, uri, MALE)

    # Valid form, no plan yet: the phone's plan page.
    _sign_form(db, add("ליאור", "שפירא", "050-555-0107", date(1988, 3, 17)), FEMALE)

    # "Yes" to a question: waiting for a doctor's note.
    noam = add("נועם", "ביטון", "050-555-0108", date(1979, 7, 5))
    _sign_form(db, noam, MALE, yes=(first_question,))

    # "Yes", and the doctor's note is in: the form counts.
    shira = add("שירה", "אברהם", "050-555-0109", date(1982, 12, 1))
    _sign_form(db, shira, FEMALE, yes=(first_question,))
    add_doctor_note(
        db, shira, check_note_image(_doctor_note()), by=owner, today=local_today()
    )
    choose_plan(db, shira, Plan.SINGLE_ENTRY, month, by=owner)

    # No form yet: no check-in until they fill it in.
    add("תמר", "דהן", "050-555-0110", date(1999, 5, 25))
    add("גיל", "רוזן", "050-555-0111", date(1975, 10, 10))

    # A customer who left.
    ronit = add("רונית", "אלון", "050-555-0112", date(1970, 8, 19))
    deactivate_customer(db, ronit, by=owner)


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
    print(f"Owner PIN: {OWNER[1]}")
    print(f"Manager PIN: {MANAGER[1]}")
    print(f"Instructor PIN: {INSTRUCTOR[1]}")


if __name__ == "__main__":
    main()
