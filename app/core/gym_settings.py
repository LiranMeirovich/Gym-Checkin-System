"""Gym settings: the values the manager edits in the admin app, stored in
the ``settings`` table (decision 0014).

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
    ValidationError,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Setting

# A deliberately loose shape check: something@domain.tld, no spaces. The
# real test of an address is whether mail to it arrives (milestone 5).
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    here; it needs no migration."""

    # Unknown keys are an error, and nothing may change a loaded instance.
    # The Strict* types mean a stored "5" is not silently read as the
    # number 5, nor true as 1.
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Shown in page titles and the report. Not set until first-run setup.
    gym_name: Annotated[StrictStr, Field(min_length=1, max_length=100)] | None = None

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
    """The current gym settings: stored values, defaults for the rest."""
    values: dict[str, object] = {}
    for row in db.scalars(select(Setting)):
        if row.key not in GymSettings.model_fields:
            raise InvalidStoredSettingError(f"unknown setting {row.key!r}")
        try:
            values[row.key] = json.loads(row.value)
        except json.JSONDecodeError as error:
            raise InvalidStoredSettingError(
                f"setting {row.key!r} is not valid JSON"
            ) from error

    try:
        return GymSettings.model_validate(values)
    except ValidationError as error:
        raise InvalidStoredSettingError(_describe(error)) from None


def _describe(error: ValidationError) -> str:
    """Which settings failed and why, without repeating the values: they
    can be email addresses, and this message ends up in logs."""
    problems = [
        f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
        for problem in error.errors(include_input=False, include_url=False)
    ]
    return "invalid stored settings: " + "; ".join(problems)
