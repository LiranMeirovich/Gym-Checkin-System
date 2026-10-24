"""Deployment config: defaults, where values come from, and validation
(decision 0013)."""

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_dev_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    settings = Settings()

    assert settings.environment == "dev"
    assert settings.database_path == Path("gym.db")
    assert settings.timezone == "Asia/Jerusalem"
    assert settings.tz == ZoneInfo("Asia/Jerusalem")
    assert settings.public_hostname is None


def test_environment_defaults_to_prod_and_then_needs_a_hostname() -> None:
    # Fails closed: no config at all means prod, which refuses to start
    # without knowing its public hostname.
    with pytest.raises(ValidationError, match="GYM_PUBLIC_HOSTNAME is required"):
        Settings()


def test_prod_with_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "checkin.example.com")

    assert Settings().environment == "prod"


def test_values_come_from_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_DATABASE_PATH", "data/test.db")
    monkeypatch.setenv("GYM_TIMEZONE", "Europe/London")

    settings = Settings()

    assert settings.database_path == Path("data/test.db")
    assert settings.timezone == "Europe/London"


def test_values_come_from_dotenv_file(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text(
        "GYM_ENVIRONMENT=dev\nGYM_TIMEZONE=Europe/London\n", encoding="utf-8"
    )

    assert Settings().timezone == "Europe/London"


def test_environment_variable_beats_dotenv_file(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_env / ".env").write_text(
        "GYM_ENVIRONMENT=dev\nGYM_TIMEZONE=Europe/London\n", encoding="utf-8"
    )
    monkeypatch.setenv("GYM_TIMEZONE", "Asia/Tokyo")

    assert Settings().timezone == "Asia/Tokyo"


def test_misspelt_key_in_dotenv_file_is_rejected(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text(
        "GYM_ENVIRONMENT=dev\nGYM_TIMEZNE=Europe/London\n", encoding="utf-8"
    )

    with pytest.raises(ValidationError, match="gym_timezne"):
        Settings()


def test_unprefixed_key_in_dotenv_file_is_rejected(isolated_env: Path) -> None:
    # .env belongs to this app alone, so anything else in it is a mistake.
    # (Known gap: an unprefixed key that matches a field name, e.g.
    # TIMEZONE=..., is silently ignored by pydantic-settings instead.)
    (isolated_env / ".env").write_text(
        "GYM_ENVIRONMENT=dev\nSMTP_HOST=smtp.example.com\n", encoding="utf-8"
    )

    with pytest.raises(ValidationError, match="smtp_host"):
        Settings()


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="environment"):
        Settings()


@pytest.mark.parametrize("timezone", ["Israel/Tel_Aviv", "Asia", "../etc/passwd"])
def test_unknown_timezone_is_rejected(
    timezone: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_TIMEZONE", timezone)

    with pytest.raises(ValidationError, match="timezone"):
        Settings()


def test_hostname_is_normalised_to_lowercase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "  CheckIn.Example.COM ")

    assert Settings().public_hostname == "checkin.example.com"


@pytest.mark.parametrize(
    "hostname",
    [
        "https://checkin.example.com",
        "checkin.example.com/",
        "checkin.example.com:8001",
        "localhost",
        "-checkin.example.com",
        "check_in.example.com",
        "checkin..example.com",
        "a" * 64 + ".example.com",
    ],
)
def test_bad_hostname_is_rejected(
    hostname: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", hostname)

    with pytest.raises(ValidationError, match="not a bare hostname"):
        Settings()


def test_get_settings_loads_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    first = get_settings()
    monkeypatch.setenv("GYM_TIMEZONE", "Asia/Tokyo")

    assert get_settings() is first
    assert get_settings().timezone == "Asia/Jerusalem"


ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_env_example_lists_every_setting() -> None:
    # Keys count whether they're set or commented out ("# GYM_X=...").
    keys = {
        line.lstrip("# ").split("=", 1)[0]
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.lstrip("# ").startswith("GYM_") and "=" in line
    }

    assert keys == {f"GYM_{name.upper()}" for name in Settings.model_fields}


def test_env_example_is_a_valid_config() -> None:
    settings = Settings(_env_file=ENV_EXAMPLE)

    assert settings.environment == "dev"


@pytest.mark.parametrize("hostname", ["10.0.0.1", "192.168.1.20"])
def test_ip_address_is_not_a_hostname(
    hostname: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", hostname)

    with pytest.raises(ValidationError, match="is an IP address"):
        Settings()


def test_blank_values_in_dotenv_file_mean_unset(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text(
        "GYM_ENVIRONMENT=dev\nGYM_TIMEZONE=\nGYM_PUBLIC_HOSTNAME=\n", encoding="utf-8"
    )

    settings = Settings()

    assert settings.timezone == "Asia/Jerusalem"
    assert settings.public_hostname is None


def test_blank_hostname_still_fails_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "")

    with pytest.raises(ValidationError, match="GYM_PUBLIC_HOSTNAME is required"):
        Settings()


def test_settings_cannot_be_changed_after_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    settings = get_settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.environment = "prod"
