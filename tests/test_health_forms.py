"""Health form rules: the form's wording, checking a filled-in form, how
long a form lasts, who signs, and the status staff and the phone see.
Names and answers are made up."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.health_forms import (
    CURRENT_VERSION,
    FORMS,
    FormField,
    FormState,
    FormVersionChangedError,
    Gender,
    InvalidHealthFormError,
    check_form,
    expires_on,
    health_form_status,
    signed_by_guardian,
)
from app.core.models import Customer, HealthForm

FORM = FORMS[CURRENT_VERSION]
ALL_NO = {question.key: False for question in FORM.questions}


def filled(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "version": CURRENT_VERSION,
        "answers": dict(ALL_NO),
        "details": {},
        "gender": "female",
        "signer_name": "Noa Levi",
        "confirmed": True,
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

    assert "Made-up Gym" in notes[0]
    assert not any("{" in note for note in notes)


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
        (date(2028, 2, 29), date(2029, 2, 27)),
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
    assert status.allows_check_in is False


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
