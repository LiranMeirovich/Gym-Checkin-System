"""Deployment config: values set once by whoever installs the system
(decision 0013).

Read from environment variables prefixed with ``GYM_``, or from a ``.env``
file in the working directory. Real environment variables win over ``.env``.
Everything is validated when the settings are first loaded, so a bad value
stops the app at startup instead of letting it run on a wrong value.

Values the manager edits in the UI (gym name, emails, lock-screen minutes)
are not here; they belong in the ``settings`` table (decision 0014).
Secrets are, as ``SecretStr`` fields, so they never show up in a repr or a
log line. The host keeps them in its environment or ``.env``; only the
production secret store waits on the hosting decision, and moving to one
only changes how these fields get their values.
"""

import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
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
        # misspelt one (GYM_TIMEZNE) or a foreign one (MAIL_SERVER). .env is
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

    # Folder the monthly reports' Excel and PDF files are saved in
    # (report-2026-11.xlsx). Relative paths are resolved against the working
    # directory the app is started from. Created when the first report is.
    reports_dir: Path = Path("reports")

    # IANA timezone for showing times (all timestamps are stored in UTC).
    timezone: str = "Asia/Jerusalem"

    # The hostname phones reach the public app on, e.g. "checkin.example.com".
    # Optional in dev; required in prod.
    public_hostname: str | None = None

    # Signs the admin app's CSRF tokens. Random, at least 32 characters;
    # generate one with
    #   uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
    # Required in prod. In dev a missing key gets a random one per run (see
    # _dev_gets_a_random_key). Changing it only makes forms on pages that
    # are already open fail once (a reload fixes them); nothing stored
    # depends on it.
    secret_key: SecretStr | None = Field(default=None, min_length=32)

    # The mail server that sends the monthly report (design doc: "Monthly
    # report"), e.g. smtp.gmail.com with the gym Google account's app
    # password. STARTTLS on ``smtp_port``; the user is also the From
    # address. Host, user and password come together or not at all.
    # Required in prod. In dev, with no host, emails are written as .eml
    # files to the outbox folder instead of being sent (app.core.email).
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _dev_gets_a_random_key(cls, data: Any) -> Any:
        # In dev, nobody should have to make up a key to try the app. In
        # prod a missing key is an error (_prod_needs_these), never this.
        if (
            isinstance(data, dict)
            and data.get("environment") == "dev"
            and not data.get("secret_key")
        ):
            return {**data, "secret_key": secrets.token_urlsafe(32)}
        return data

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

    @field_validator("smtp_host", "smtp_user")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        # Both reach the SMTP conversation; the user is a From header too.
        if value is not None and (
            value != value.strip() or any(c.isspace() for c in value)
        ):
            raise ValueError("must not contain spaces or line breaks")
        return value

    @field_validator("smtp_user")
    @classmethod
    def _user_is_an_address(cls, value: str | None) -> str | None:
        # It's the From address, so the recipients see who sent it.
        if value is not None and value.count("@") != 1:
            raise ValueError("must be the sending email address")
        return value

    @model_validator(mode="after")
    def _smtp_all_or_nothing(self) -> Self:
        given = {
            name: getattr(self, name) is not None
            for name in ("smtp_host", "smtp_user", "smtp_password")
        }
        if any(given.values()) and not all(given.values()):
            missing = ", ".join(f"GYM_{n.upper()}" for n, ok in given.items() if not ok)
            raise ValueError(f"SMTP is only partly set up: {missing} missing")
        return self

    @model_validator(mode="after")
    def _prod_needs_these(self) -> Self:
        if self.environment != "prod":
            return self
        # Every missing one at once, so a new install is fixed in one go.
        missing = [
            f"GYM_{name.upper()} is required in prod"
            for name in (
                "public_hostname",
                "secret_key",
                "smtp_host",
                "smtp_user",
                "smtp_password",
            )
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError("; ".join(missing))
        return self

    @property
    def tz(self) -> ZoneInfo:
        """The display timezone as a ``ZoneInfo``."""
        return ZoneInfo(self.timezone)

    @property
    def sends_email(self) -> bool:
        """Whether emails go through SMTP (otherwise to the dev outbox)."""
        return self.smtp_host is not None

    @property
    def signing_key(self) -> bytes:
        """``secret_key`` as bytes, for HMAC. Always set once loaded: prod
        requires it and dev makes one up."""
        if self.secret_key is None:
            raise RuntimeError("no secret key loaded")
        return self.secret_key.get_secret_value().encode()


@lru_cache
def get_settings() -> Settings:
    """The settings for this process, loaded and validated once.

    The one way the rest of the code reads deployment config. Tests build
    their own ``Settings`` or call ``get_settings.cache_clear()``.
    """
    return Settings()
