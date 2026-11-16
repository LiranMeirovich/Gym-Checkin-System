"""Deployment config: defaults, where values come from, and validation
(decision 0013)."""

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

# Made up and obviously not random; real keys never appear in the repo.
TEST_KEY = "x" * 40
TEST_DATABASE_KEY = "ab" * 32
TEST_BACKUP_PASSWORD = "not-a-real-backup-password-" + "x" * 8


def set_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """A made-up mail server, which prod requires."""
    monkeypatch.setenv("GYM_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GYM_SMTP_USER", "gym@example.com")
    monkeypatch.setenv("GYM_SMTP_PASSWORD", "not-a-real-password")


def test_dev_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    settings = Settings()

    assert settings.environment == "dev"
    assert settings.database_path == Path("gym.db")
    assert settings.timezone == "Asia/Jerusalem"
    assert settings.tz == ZoneInfo("Asia/Jerusalem")
    assert settings.public_hostname is None


def test_environment_defaults_to_prod_and_then_needs_a_hostname_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fails closed: no config at all means prod, which refuses to start
    # without its public hostname and keys. All are reported at once.
    monkeypatch.delenv("GYM_DATABASE_KEY")  # set for every test by conftest
    with pytest.raises(ValidationError) as error:
        Settings()

    assert "GYM_PUBLIC_HOSTNAME is required in prod" in str(error.value)
    assert "GYM_SECRET_KEY is required in prod" in str(error.value)
    assert "GYM_DATABASE_KEY is required in prod" in str(error.value)
    assert "GYM_BACKUP_PASSWORD is required in prod" in str(error.value)
    assert "GYM_SMTP_PASSWORD is required in prod" in str(error.value)


def test_prod_with_hostname_keys_and_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "checkin.example.com")
    monkeypatch.setenv("GYM_SECRET_KEY", TEST_KEY)
    monkeypatch.setenv("GYM_DATABASE_KEY", TEST_DATABASE_KEY)
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", TEST_BACKUP_PASSWORD)
    set_smtp(monkeypatch)

    settings = Settings()

    assert settings.environment == "prod"
    assert settings.signing_key == TEST_KEY.encode()
    assert settings.database_key_hex == TEST_DATABASE_KEY
    assert settings.makes_backups


def test_dev_without_a_database_key_is_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.delenv("GYM_DATABASE_KEY")  # set for every test by conftest

    assert Settings().database_key_hex is None


@pytest.mark.parametrize(
    "key",
    [
        "ab" * 31,  # 62 characters
        "ab" * 33,  # 66 characters
        "zz" * 32,  # not hex
        "ab" * 31 + "'\"",  # would break out of PRAGMA key's quotes
    ],
)
def test_a_bad_database_key_is_rejected(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_DATABASE_KEY", key)

    with pytest.raises(ValidationError, match="64 hex characters"):
        Settings()


def test_the_database_key_never_shows_in_a_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_DATABASE_KEY", TEST_DATABASE_KEY)

    assert TEST_DATABASE_KEY not in repr(Settings())
    assert TEST_DATABASE_KEY not in str(Settings().model_dump())


def test_prod_needs_a_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "checkin.example.com")

    with pytest.raises(ValidationError, match="GYM_SECRET_KEY is required in prod"):
        Settings()


def test_a_short_secret_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_SECRET_KEY", "x" * 31)

    with pytest.raises(ValidationError, match="at least 32"):
        Settings()


def test_dev_without_a_key_gets_a_random_one_each_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    first, second = Settings(), Settings()

    assert len(first.signing_key) >= 32
    assert first.signing_key != second.signing_key


def test_dev_keeps_a_key_it_was_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_SECRET_KEY", TEST_KEY)

    assert Settings().signing_key == TEST_KEY.encode()


def test_the_secret_key_never_shows_in_a_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_SECRET_KEY", TEST_KEY)

    assert TEST_KEY not in repr(Settings())
    assert TEST_KEY not in str(Settings().model_dump())


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
        "GYM_ENVIRONMENT=dev\nMAIL_SERVER=smtp.example.com\n", encoding="utf-8"
    )

    with pytest.raises(ValidationError, match="mail_server"):
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
    monkeypatch.setenv("GYM_SECRET_KEY", TEST_KEY)
    monkeypatch.setenv("GYM_DATABASE_KEY", TEST_DATABASE_KEY)
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", TEST_BACKUP_PASSWORD)
    set_smtp(monkeypatch)

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


def test_dev_without_smtp_saves_emails_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    settings = Settings()

    assert settings.smtp_port == 587
    assert not settings.sends_email


def test_dev_with_smtp_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    set_smtp(monkeypatch)

    settings = Settings()

    assert settings.sends_email
    assert settings.smtp_user == "gym@example.com"


@pytest.mark.parametrize("left_out", ["GYM_SMTP_USER", "GYM_SMTP_PASSWORD"])
def test_smtp_set_up_only_partly_is_rejected(
    left_out: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    set_smtp(monkeypatch)
    monkeypatch.delenv(left_out)

    with pytest.raises(ValidationError, match=f"partly set up: {left_out} missing"):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GYM_SMTP_USER", "not-an-address"),
        ("GYM_SMTP_USER", "gym@example.com\nBcc: x@example.com"),
        ("GYM_SMTP_HOST", "smtp.example.com extra"),
        ("GYM_SMTP_PORT", "0"),
        ("GYM_SMTP_PORT", "70000"),
    ],
)
def test_bad_smtp_values_are_rejected(
    name: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    set_smtp(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_the_smtp_password_never_shows_in_a_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    set_smtp(monkeypatch)

    assert "not-a-real-password" not in repr(Settings())


def test_dev_without_a_backup_password_makes_no_backups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")

    settings = Settings()

    assert not settings.makes_backups
    assert settings.backups_dir == Path("backups")


def test_a_short_backup_password_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Zip's key stretching is weak, so only a long password is safe.
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", "x" * 31)

    with pytest.raises(ValidationError, match="backup_password"):
        Settings()


def test_the_backup_password_never_shows_in_a_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    monkeypatch.setenv("GYM_BACKUP_PASSWORD", TEST_BACKUP_PASSWORD)

    settings = Settings()

    assert settings.makes_backups
    assert TEST_BACKUP_PASSWORD not in repr(settings)
