"""Health form rules: the form's wording, checking a filled-in form, how
long a form lasts, who signs, and the status staff and the phone see.
Names and answers are made up."""

import io
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.activity_log import Action, Target
from app.core.customers import CustomerInactiveError
from app.core.db import get_engine
from app.core.doctor_notes import NoNoteNeededError, accept_form
from app.core.health_forms import (
    CURRENT_VERSION,
    FORMS,
    FormField,
    FormState,
    FormVersionChangedError,
    Gender,
    HealthFormStatus,
    InvalidHealthFormError,
    check_form,
    expires_on,
    health_form_status,
    list_forms,
    open_form_document,
    save_form,
    signed_by_guardian,
)
from app.core.models import (
    ActivityLogEntry,
    Customer,
    DoctorNote,
    HealthForm,
    HealthFormAcceptance,
    ImageType,
    StaffUser,
)
from app.core.permissions import Role

FORM = FORMS[CURRENT_VERSION]
ALL_NO = {question.key: False for question in FORM.questions}


def signature_png(*, drawn: bool = True, size: tuple[int, int] = (600, 240)) -> bytes:
    """A made-up signature: a zigzag on a transparent canvas, as the
    phone's signature pad sends it."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    if drawn:
        ImageDraw.Draw(image).line([(20, 100), (100, 30), (180, 90)], "black", 5)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


SIGNATURE = signature_png()
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def filled(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "version": CURRENT_VERSION,
        "answers": dict(ALL_NO),
        "details": {},
        "gender": "female",
        "signer_name": "Noa Levi",
        "confirmed": True,
        "signature_png": SIGNATURE,
    }
    return fields | changes


# ── The form's wording ─────────────────────────────────────────────────


def test_the_current_form_has_the_official_fifteen_questions() -> None:
    assert len(FORM.questions) == 15
    assert len({q.key for q in FORM.questions}) == 15
    assert [q.key for q in FORM.questions if q.has_details] == [
        "doctor_advised_no_exercise",
        "other",
    ]


def test_the_gym_name_comes_from_settings() -> None:
    notes = FORM.notes("Made-up Gym")

    assert "לחדר כושר Made-up Gym" in notes[0]
    assert not any("{" in note for note in notes)


def test_without_a_gym_name_the_form_says_the_gym() -> None:
    assert "לחדר הכושר" in FORM.notes(None)[0]


def test_the_guardian_consent_names_the_trainee() -> None:
    assert "Noa Levi" in FORM.consent("Noa Levi")


# ── Checking a filled-in form ──────────────────────────────────────────


def test_a_complete_form_passes() -> None:
    checked = check_form(**filled())

    assert checked.form is FORM
    assert checked.gender is Gender.FEMALE
    assert checked.needs_doctor_note is False
    assert checked.answers_json_value() == {
        "answers": ALL_NO,
        "details": {},
        "gender": "female",
    }


def test_any_yes_needs_a_doctors_note() -> None:
    answers = ALL_NO | {"diabetes": True}

    assert check_form(**filled(answers=answers)).needs_doctor_note is True


def test_answers_are_kept_in_the_forms_order() -> None:
    reversed_answers = dict(reversed(list(ALL_NO.items())))

    checked = check_form(**filled(answers=reversed_answers))

    assert list(checked.answers) == [q.key for q in FORM.questions]


def test_hebrew_latin_and_punctuation_are_accepted() -> None:
    checked = check_form(
        **filled(
            signer_name="\u05e0\u05d5\u05e2\u05d4 Levi-Cohen (O'Brien)",
            details={"other": "\u05e0\u05d9\u05ea\u05d5\u05d7, 2020; 3."},
        )
    )

    assert checked.signer_name == "\u05e0\u05d5\u05e2\u05d4 Levi-Cohen (O'Brien)"


def test_the_name_and_details_are_tidied() -> None:
    checked = check_form(
        **filled(
            signer_name="  Noa   Levi ",
            details={
                "other": "  knee surgery 2020 ",
                "doctor_advised_no_exercise": " ",
            },
        )
    )

    assert checked.signer_name == "Noa Levi"
    assert checked.details == {"other": "knee surgery 2020"}


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"answers": {k: v for k, v in ALL_NO.items() if k != "stroke"}}, "answers"),
        ({"answers": ALL_NO | {"made_up": False}}, "answers"),
        ({"answers": ALL_NO | {"stroke": "no"}}, "answers"),
        ({"answers": ALL_NO | {"stroke": 0}}, "answers"),
        ({"details": {"diabetes": "type 2"}}, "details"),
        ({"details": {"other": "x" * 201}}, "details"),
        ({"gender": "other"}, "gender"),
        ({"gender": ""}, "gender"),
        ({"signer_name": "   "}, "signer_name"),
        ({"signer_name": "x" * 101}, "signer_name"),
        ({"confirmed": False}, "confirmed"),
        ({"signer_name": "\u041d\u0430\u0442\u0430\u0448\u0430"}, "signer_name"),
        ({"signer_name": "Noa \u202eiveL"}, "signer_name"),
        ({"signer_name": "Noa \U0001f600"}, "signer_name"),
        ({"details": {"other": "line\nbreak"}}, "details"),
        ({"details": {"other": "\u0645\u062d\u0645\u062f"}}, "details"),
        ({"signature_png": signature_png(drawn=False)}, "signature"),
        ({"signature_png": b""}, "signature"),
        ({"signature_png": PNG_HEADER + b" not really"}, "signature"),
        ({"signature_png": b"GIF89a"}, "signature"),
        ({"signature_png": signature_png(size=(30, 30))}, "signature"),
    ],
    ids=[
        "a question unanswered",
        "an unknown question",
        "an answer that isn't yes or no",
        "a number for an answer",
        "details on a question without a line",
        "details too long",
        "an unknown gender",
        "no gender",
        "no name",
        "name too long",
        "not confirmed",
        "a cyrillic name",
        "a bidi override in the name",
        "an emoji in the name",
        "a control character in the details",
        "arabic details",
        "a blank signature",
        "no signature",
        "a broken png",
        "not a png",
        "a tiny signature",
    ],
)
def test_a_bad_field_is_refused(changes: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidHealthFormError) as refused:
        check_form(**filled(**changes))

    assert refused.value.fields == {FormField(field)}


def test_every_bad_field_is_named_at_once() -> None:
    with pytest.raises(InvalidHealthFormError) as refused:
        check_form(**filled(gender="x", signer_name="", confirmed=False))

    assert refused.value.fields == {
        FormField.GENDER,
        FormField.SIGNER_NAME,
        FormField.CONFIRMED,
    }


def test_an_old_version_is_refused() -> None:
    with pytest.raises(FormVersionChangedError):
        check_form(**filled(version="2020-01"))


# ── How long a form lasts, and who signs ───────────────────────────────


@pytest.mark.parametrize(
    ("signed", "last_day"),
    [
        (date(2026, 11, 4), date(2027, 11, 3)),
        (date(2026, 1, 1), date(2026, 12, 31)),
        (date(2026, 3, 1), date(2027, 2, 28)),
        (date(2028, 2, 29), date(2029, 2, 28)),
        (date(2026, 12, 31), date(2027, 12, 30)),
    ],
)
def test_a_form_lasts_twelve_months(signed: date, last_day: date) -> None:
    assert expires_on(signed) == last_day


def customer_born(born: date) -> Customer:
    return Customer(first_name="Noa", last_name="Levi", date_of_birth=born)


@pytest.mark.parametrize(
    ("signed", "guardian"),
    [
        (date(2026, 11, 3), True),
        (date(2026, 11, 4), False),
        (date(2027, 1, 1), False),
    ],
    ids=["the day before 18", "the 18th birthday", "after"],
)
def test_a_parent_signs_for_an_under_18(signed: date, guardian: bool) -> None:
    assert signed_by_guardian(customer_born(date(2008, 11, 4)), signed) is guardian


# ── Status ─────────────────────────────────────────────────────────────


@pytest.fixture
def db(migrated_db: Path) -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


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


def add_form(
    db: Session, customer: Customer, signed: date, *, yes: bool = False
) -> HealthForm:
    form = HealthForm(
        customer_id=customer.id,
        form_version=CURRENT_VERSION,
        answers_json="{}",
        needs_doctor_note=yes,
        signer_name="Noa Levi",
        signed_by_guardian=False,
        signed_on=signed,
        expires_on=expires_on(signed),
        document=b"%PDF-1.7 made-up",
    )
    db.add(form)
    db.commit()
    return form


def test_no_form_is_missing(db: Session, customer: Customer) -> None:
    status = health_form_status(db, customer, date(2026, 11, 4))

    assert status.state is FormState.MISSING
    assert status.valid_until is None
    assert status.allows_check_in is False


def test_a_form_is_valid_through_its_last_day(db: Session, customer: Customer) -> None:
    add_form(db, customer, date(2026, 11, 4))

    on_last_day = health_form_status(db, customer, date(2027, 11, 3))
    day_after = health_form_status(db, customer, date(2027, 11, 4))

    assert on_last_day.state is FormState.VALID
    assert on_last_day.valid_until == date(2027, 11, 3)
    assert on_last_day.allows_check_in is True
    assert day_after.state is FormState.MISSING


def test_a_form_with_a_yes_needs_a_doctors_note(
    db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)

    status = health_form_status(db, customer, date(2026, 11, 4))

    assert status.state is FormState.NEEDS_DOCTOR_NOTE
    assert status.valid_until == date(2027, 11, 3)
    # It lets the customer in meanwhile, and the phone sees it as valid
    # (decision 0041).
    assert status.allows_check_in is True
    assert status.as_entry_status() == HealthFormStatus(
        FormState.VALID, date(2027, 11, 3)
    )


def test_only_staff_who_review_forms_see_one_waiting() -> None:
    waiting = HealthFormStatus(FormState.NEEDS_DOCTOR_NOTE, date(2027, 11, 3))
    valid = HealthFormStatus(FormState.VALID, date(2027, 11, 3))

    assert waiting.as_seen_by(Role.OWNER) == waiting
    assert waiting.as_seen_by("manager") == waiting
    assert waiting.as_seen_by(Role.INSTRUCTOR) == valid
    assert valid.as_seen_by(Role.INSTRUCTOR) == valid


def test_only_a_missing_form_blocks_check_in() -> None:
    missing = HealthFormStatus(FormState.MISSING, None)

    assert missing.allows_check_in is False
    assert missing.as_entry_status() == missing


def test_the_newest_form_counts(db: Session, customer: Customer) -> None:
    add_form(db, customer, date(2026, 1, 10))
    add_form(db, customer, date(2026, 6, 1), yes=True)

    status = health_form_status(db, customer, date(2026, 7, 1))

    assert status.state is FormState.NEEDS_DOCTOR_NOTE


def test_a_new_form_replaces_one_that_needed_a_note(
    db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 1, 10), yes=True)
    add_form(db, customer, date(2026, 6, 1))

    status = health_form_status(db, customer, date(2026, 7, 1))

    assert status.state is FormState.VALID
    assert status.valid_until == date(2027, 5, 31)


def add_note(db: Session, form: HealthForm) -> None:
    staff = StaffUser(
        display_name="Yoni",
        role=Role.INSTRUCTOR,
        pin_hash="$argon2id$v=19$m=65536,t=3,p=4$fake",
    )
    db.add(staff)
    db.flush()
    db.add(
        DoctorNote(
            health_form_id=form.id,
            image=b"\xff\xd8\xff made up",
            content_type=ImageType.JPEG,
            staff_user_id=staff.id,
        )
    )
    db.commit()


def test_a_doctors_note_makes_a_form_with_a_yes_valid(
    db: Session, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4), yes=True)
    add_note(db, form)

    status = health_form_status(db, customer, date(2026, 11, 4))

    assert status.state is FormState.VALID
    assert status.valid_until == date(2027, 11, 3)
    assert status.allows_check_in is True


def test_a_note_on_an_older_form_doesnt_clear_a_newer_yes(
    db: Session, customer: Customer
) -> None:
    older = add_form(db, customer, date(2026, 1, 10), yes=True)
    add_note(db, older)
    add_form(db, customer, date(2026, 6, 1), yes=True)

    status = health_form_status(db, customer, date(2026, 7, 1))

    assert status.state is FormState.NEEDS_DOCTOR_NOTE


def a_manager(db: Session) -> StaffUser:
    manager = StaffUser(
        display_name="Rona",
        role=Role.MANAGER,
        pin_hash="$argon2id$v=19$m=65536,t=3,p=4$fake",
    )
    db.add(manager)
    db.flush()
    return manager


def test_the_managers_acceptance_makes_a_form_with_a_yes_valid(
    db: Session, customer: Customer
) -> None:
    form = add_form(db, customer, date(2026, 11, 4), yes=True)
    manager = a_manager(db)

    accepted = accept_form(db, customer, by=manager, today=date(2026, 11, 5))

    assert accepted.health_form_id == form.id
    assert accepted.staff_user_id == manager.id
    status = health_form_status(db, customer, date(2026, 11, 5))
    assert status == HealthFormStatus(FormState.VALID, date(2027, 11, 3))
    entry = db.scalars(select(ActivityLogEntry)).one()
    assert (entry.action, entry.target_type, entry.target_id) == (
        Action.HEALTH_FORM_ACCEPT,
        Target.HEALTH_FORM,
        form.id,
    )
    assert entry.staff_user_id == manager.id


@pytest.mark.parametrize("yes", [False, True])
def test_only_a_form_waiting_for_review_can_be_accepted(
    db: Session, customer: Customer, yes: bool
) -> None:
    # A form without a "yes", or one already accepted, isn't waiting.
    add_form(db, customer, date(2026, 11, 4), yes=yes)
    manager = a_manager(db)
    if yes:
        accept_form(db, customer, by=manager, today=date(2026, 11, 4))

    with pytest.raises(NoNoteNeededError) as refused:
        accept_form(db, customer, by=manager, today=date(2026, 11, 4))

    assert refused.value.state is FormState.VALID
    assert len(db.scalars(select(HealthFormAcceptance)).all()) == (1 if yes else 0)


def test_a_missing_form_cant_be_accepted(db: Session, customer: Customer) -> None:
    with pytest.raises(NoNoteNeededError) as refused:
        accept_form(db, customer, by=a_manager(db), today=date(2026, 11, 4))

    assert refused.value.state is FormState.MISSING


def test_an_inactive_customers_form_cant_be_accepted(
    db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 11, 4), yes=True)
    customer.active = False

    with pytest.raises(CustomerInactiveError):
        accept_form(db, customer, by=a_manager(db), today=date(2026, 11, 4))

    assert db.scalars(select(HealthFormAcceptance)).all() == []


def test_accepting_an_older_form_doesnt_clear_a_newer_yes(
    db: Session, customer: Customer
) -> None:
    add_form(db, customer, date(2026, 1, 10), yes=True)
    accept_form(db, customer, by=a_manager(db), today=date(2026, 2, 1))
    add_form(db, customer, date(2026, 6, 1), yes=True)

    status = health_form_status(db, customer, date(2026, 7, 1))

    assert status.state is FormState.NEEDS_DOCTOR_NOTE


def test_another_customers_form_doesnt_count(db: Session, customer: Customer) -> None:
    other = Customer(
        first_name="Dan",
        last_name="Cohen",
        phone="+972521111111",
        date_of_birth=date(1985, 1, 1),
    )
    db.add(other)
    db.commit()
    add_form(db, other, date(2026, 11, 4))

    assert health_form_status(db, customer, date(2026, 11, 4)).state is (
        FormState.MISSING
    )


def test_the_signature_is_re_encoded_as_a_png() -> None:
    checked = check_form(**filled())

    assert checked.signature_png.startswith(PNG_HEADER)
    assert checked.signature_png != SIGNATURE


# ── Saving and opening a form ──────────────────────────────────────────


def test_a_saved_form_keeps_its_answers_dates_and_snapshot(
    db: Session, customer: Customer
) -> None:
    checked = check_form(
        **filled(answers=ALL_NO | {"other": True}, details={"other": "knee"})
    )

    form = save_form(db, customer, checked, today=date(2026, 11, 4))
    db.commit()

    assert form.form_version == CURRENT_VERSION
    assert json.loads(form.answers_json) == {
        "answers": ALL_NO | {"other": True},
        "details": {"other": "knee"},
        "gender": "female",
    }
    assert form.needs_doctor_note is True
    assert form.signer_name == "Noa Levi"
    assert form.signed_by_guardian is False
    assert form.signed_on == date(2026, 11, 4)
    assert form.expires_on == date(2027, 11, 3)
    assert form.document.startswith(b"%PDF-")


def test_a_parent_signs_for_an_under_18_customer(
    db: Session, customer: Customer
) -> None:
    customer.date_of_birth = date(2010, 5, 1)
    db.commit()

    form = save_form(
        db,
        customer,
        check_form(**filled(signer_name="Dana Levi")),
        today=date(2026, 11, 4),
    )

    assert form.signed_by_guardian is True
    assert form.signer_name == "Dana Levi"


def test_an_inactive_customer_cant_sign(db: Session, customer: Customer) -> None:
    customer.active = False
    db.commit()

    with pytest.raises(CustomerInactiveError):
        save_form(db, customer, check_form(**filled()), today=date(2026, 11, 4))


def test_forms_are_listed_newest_first(db: Session, customer: Customer) -> None:
    older = add_form(db, customer, date(2026, 1, 10))
    newer = add_form(db, customer, date(2026, 6, 1))

    assert list_forms(db, customer) == [newer, older]


def test_opening_a_form_is_logged(db: Session, customer: Customer) -> None:
    manager = StaffUser(display_name="Dana", role=Role.MANAGER, pin_hash="$argon2id$x")
    db.add(manager)
    db.flush()
    form = add_form(db, customer, date(2026, 11, 4))

    document = open_form_document(db, form, by=manager)

    assert document.startswith(b"%PDF-")
    entry = db.scalars(select(ActivityLogEntry)).one()
    assert entry.staff_user_id == manager.id
    assert entry.action == Action.HEALTH_FORM_OPEN
    assert (entry.target_type, entry.target_id) == (Target.HEALTH_FORM, form.id)
