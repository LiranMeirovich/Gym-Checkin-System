"""Gym settings: the values the manager edits in the admin app, stored in
the ``settings`` table (decisions 0014, 0016).

``GymSettings`` is the one place a setting is defined: its key, type,
default and validation. The table only holds values; a key with no row
uses the default here. Deployment config (paths, timezone, hostname) is a
different thing and lives in ``app.core.config``.

Settings are read from the database on every request, not cached, so a
change saved in the admin app reaches the public app straight away.
"""

import json
import re
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
)
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.models import Setting

# A plain ASCII address: dot-atom characters before the "@", letters,
# digits and hyphens in each part of the domain. Stricter than the email
# standard on purpose: commas, angle brackets, quotes, spaces and control
# characters would change the meaning of a To: header (an extra recipient,
# an injected header) once the report is emailed (milestone 5).
_EMAIL = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9](-*[A-Za-z0-9])*(\.[A-Za-z0-9](-*[A-Za-z0-9])*)+"
)


def _email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not _EMAIL.fullmatch(value):
        raise ValueError("not an email address")
    return value


def _no_duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    lowered = [value.lower() for value in values]
    if len(set(lowered)) != len(lowered):
        raise ValueError("the same address is listed twice")
    return values


Email = Annotated[StrictStr, AfterValidator(_email)]


class GymSettings(BaseModel):
    """Every gym setting, with its default. A new setting is a new field
    here; it needs no migration. Removing or renaming one does: see the
    /migration skill."""

    # Unknown keys are an error, and nothing may change a loaded instance.
    # The Strict* types mean a stored "5" is not silently read as the
    # number 5, nor true as 1.
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Shown in page titles and the report. Not set until first-run setup.
    # Surrounding spaces are trimmed first, so "   " counts as empty.
    gym_name: (
        Annotated[
            str,
            StringConstraints(
                strict=True, strip_whitespace=True, min_length=1, max_length=100
            ),
        ]
        | None
    ) = None

    # Gets the monthly report first, to check and approve.
    manager_email: Email | None = None

    # Get the report after the manager approves it.
    report_recipients: Annotated[tuple[Email, ...], AfterValidator(_no_duplicates)] = ()

    # Minutes without activity before the admin app locks (design doc:
    # "Staff login and lock screen").
    lock_screen_minutes: Annotated[StrictInt, Field(ge=1, le=60)] = 5


class InvalidStoredSettingError(RuntimeError):
    """The settings table holds a row the code can't use: an unknown key,
    text that isn't JSON, or a value that fails validation. Raised instead
    of falling back to a default, so a bad value is noticed and fixed."""


def load_gym_settings(db: Session) -> GymSettings:
    """The current gym settings: stored values, defaults for the rest.

    Raises ``InvalidStoredSettingError`` if any row is unusable. Every
    page uses this one, except the settings screen, which uses
    ``load_gym_settings_for_editing`` so a bad row can be repaired.
    """
    settings, problems = load_gym_settings_for_editing(db)
    if problems:
        raise InvalidStoredSettingError("invalid stored settings: " + _join(problems))
    return settings


def load_gym_settings_for_editing(
    db: Session,
) -> tuple[GymSettings, dict[str, str]]:
    """The settings, plus what's wrong with any stored row, for the
    settings screen only.

    A row that's unusable doesn't stop the load: its setting shows the
    default, and ``problems`` says why (keyed like
    ``InvalidSettingsChangeError.problems``), so the screen can show the
    error next to the field and the manager can save a good value over it.
    """
    values: dict[str, object] = {}
    problems: dict[str, str] = {}
    # populate_existing: update_gym_settings writes with a plain INSERT,
    # which doesn't refresh Setting objects this session already holds, so
    # a load after a save in the same request must re-read every row.
    query = select(Setting).execution_options(populate_existing=True)
    for row in db.scalars(query):
        if row.key not in GymSettings.model_fields:
            # Usually a setting removed from the code without a migration
            # deleting its row.
            problems[row.key] = "unknown setting"
            continue
        try:
            value = json.loads(row.value)
        except json.JSONDecodeError:
            # No exception chaining: JSONDecodeError keeps the whole stored
            # text, and these errors end up in logs.
            problems[row.key] = "not valid JSON"
            continue
        # Each row on its own, so one bad row doesn't hide the good ones.
        try:
            GymSettings.model_validate({row.key: value})
        except ValidationError as error:
            problems.update(_problems(error))
            continue
        values[row.key] = value

    return GymSettings.model_validate(values), problems


class InvalidSettingsChangeError(ValueError):
    """A requested change was refused; nothing was written.

    ``problems`` maps each failing setting (``report_recipients.1`` for one
    item of a list) to what's wrong with it, for the settings screen to
    show next to the field.
    """

    def __init__(self, problems: dict[str, str]) -> None:
        super().__init__("invalid settings change: " + _join(problems))
        self.problems = problems


def update_gym_settings(db: Session, changes: dict[str, object]) -> None:
    """Validate ``changes`` and write them, inside the caller's transaction.

    Values must already have their Python type: an ``int`` for minutes, a
    list of strings for recipients. The strict types refuse ``"10"``, so a
    route converts form fields first (and reports a bad number itself).

    All or nothing: if any change is invalid (or names an unknown setting),
    nothing is written and ``InvalidSettingsChangeError`` says why. A change
    to the value already stored is skipped, so ``updated_at`` only moves
    when something really changed. ``None`` clears an optional setting by
    deleting its row, so it goes back to following the default.

    Each change is validated on its own, not together with the rest of the
    stored settings, so a bad row written by hand can be fixed from the
    settings screen (see ``load_gym_settings_for_editing``). No rule spans
    two settings yet; one that does would need checking against the stored
    values here.

    TODO(activity log): record each change, with its before and after
    value, once the activity log exists (CLAUDE.md follow-ups).
    """
    try:
        validated = GymSettings.model_validate(changes)
    except ValidationError as error:
        raise InvalidSettingsChangeError(_problems(error)) from None

    # mode="json" turns tuples into lists, so the stored text is plain JSON.
    new_values = validated.model_dump(mode="json", include=set(changes))
    cleared = [key for key, value in new_values.items() if value is None]
    if cleared:
        db.execute(delete(Setting).where(Setting.key.in_(cleared)))

    rows = [
        # ensure_ascii=False keeps Hebrew readable in a database browser.
        {"key": key, "value": json.dumps(value, ensure_ascii=False)}
        for key, value in new_values.items()
        if value is not None
    ]
    if rows:
        now = utc_now()
        # One statement, so two saves of a key that has no row yet can't
        # both try to insert it. The WHERE skips rows whose value is
        # already the same, which leaves their updated_at alone.
        statement = insert(Setting).values([{**row, "updated_at": now} for row in rows])
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[Setting.key],
                set_={"value": statement.excluded.value, "updated_at": now},
                where=Setting.value != statement.excluded.value,
            )
        )


def _problems(error: ValidationError) -> dict[str, str]:
    """Which settings failed and why, without repeating the values: they
    can be email addresses, and these messages end up in logs."""
    return {
        ".".join(str(part) for part in problem["loc"]): problem["msg"]
        for problem in error.errors(include_input=False, include_url=False)
    }


def _join(problems: dict[str, str]) -> str:
    return "; ".join(f"{key}: {message}" for key, message in problems.items())
