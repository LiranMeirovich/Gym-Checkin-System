"""Deployment config: values set once by whoever installs the system
(decision 0013).

Read from environment variables prefixed with ``GYM_``, or from a ``.env``
file in the working directory. Real environment variables win over ``.env``.
Everything is validated when the settings are first loaded, so a bad value
stops the app at startup instead of letting it run on a wrong value.

Values the manager edits in the UI (gym name, emails, lock-screen minutes)
are not here; they belong in the ``settings`` table (decision 0014).
Secrets are not here either, until the hosting decision settles where they
live.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# One DNS label: letters, digits and inner hyphens, at most 63 characters.
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
# A full hostname with at least two labels, e.g. "checkin.example.com".
# No scheme, port or path: this is compared against the Host header later.
_HOSTNAME = re.compile(rf"^{_LABEL}(\.{_LABEL})+$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GYM_",
        env_file=".env",
        env_file_encoding="utf-8",
        # An unknown key in the .env *file* is an error, not ignored: a
        # misspelt one (GYM_TIMEZNE) or a foreign one (SMTP_HOST). .env is
        # ours alone. Known gaps, both silently ignored: an unprefixed key
        # that matches a field name (TIMEZONE), and any misspelt *real*
        # environment variable, since those are only read by field name.
        extra="forbid",
        # A blank value ("GYM_PUBLIC_HOSTNAME=") means unset, so the default
        # (or prod's "required" check) applies instead of an empty string.
        env_ignore_empty=True,
        # One instance is cached and shared by the whole process
        # (get_settings), so nothing may change it after loading.
        frozen=True,
    )

    # "prod" is the default so a missing setting fails closed: a production
    # install that forgets GYM_ENVIRONMENT gets the strict checks, not dev's.
    environment: Literal["dev", "prod"] = "prod"

    # SQLite database file. Relative paths are resolved against the
    # working directory the app is started from.
    database_path: Path = Path("gym.db")

    # IANA timezone for showing times (all timestamps are stored in UTC).
    timezone: str = "Asia/Jerusalem"

    # The hostname phones reach the public app on, e.g. "checkin.example.com".
    # Optional in dev; required in prod.
    public_hostname: str | None = None

    @field_validator("timezone")
    @classmethod
    def _timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        # OSError: a zone *folder* such as "Asia" reaches the file system
        # and fails there (PermissionError on Windows) instead of not-found.
        except (ZoneInfoNotFoundError, ValueError, OSError) as error:
            raise ValueError(f"unknown timezone {value!r}") from error
        return value

    @field_validator("public_hostname")
    @classmethod
    def _hostname_is_bare(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if len(value) > 253 or not _HOSTNAME.fullmatch(value):
            raise ValueError(
                f"{value!r} is not a bare hostname (expected e.g. "
                f"'checkin.example.com', without https:// or a path)"
            )
        # The regex also matches IPv4 addresses ("10.0.0.1"). No real
        # top-level domain is all digits, so that tells them apart. Phones
        # must come in through the tunnel's DNS name, never a bare IP.
        if value.rsplit(".", 1)[-1].isdigit():
            raise ValueError(f"{value!r} is an IP address, not a hostname")
        return value

    @model_validator(mode="after")
    def _prod_needs_hostname(self) -> Self:
        if self.environment == "prod" and self.public_hostname is None:
            raise ValueError("GYM_PUBLIC_HOSTNAME is required in prod")
        return self

    @property
    def tz(self) -> ZoneInfo:
        """The display timezone as a ``ZoneInfo``."""
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    """The settings for this process, loaded and validated once.

    The one way the rest of the code reads deployment config. Tests build
    their own ``Settings`` or call ``get_settings.cache_clear()``.
    """
    return Settings()
