"""Staff PINs: format rules, hashing, checking and rehashing. Every PIN
here is made up."""

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError

from app.core.pins import (
    InvalidPinError,
    hash_pin,
    needs_rehash,
    pin_matches,
    rehash_pin,
    validate_pin,
)

# ── Format rules ────────────────────────────────────────────────────────


@pytest.mark.parametrize("pin", ["482913", "048291", "482913570461", "135790"])
def test_good_pins_are_accepted(pin: str) -> None:
    validate_pin(pin)


@pytest.mark.parametrize(
    "pin",
    [
        "",
        "48291",  # too short
        "4829135704612",  # too long
        "48 291",
        "48291a",
        " 482913",
        "482913\n",
        "٤٨٢٩١٣",  # Arabic-Indic digits
        "４８２９１３",  # full-width digits
    ],
)
def test_pins_that_are_not_6_to_12_ascii_digits_are_refused(pin: str) -> None:
    with pytest.raises(InvalidPinError, match="6 to 12 digits"):
        validate_pin(pin)


def test_a_pin_must_be_a_string() -> None:
    with pytest.raises(InvalidPinError):
        validate_pin(482913)  # type: ignore[arg-type]


@pytest.mark.parametrize("pin", ["000000", "777777777"])
def test_one_digit_repeated_is_refused(pin: str) -> None:
    with pytest.raises(InvalidPinError, match="repeated"):
        validate_pin(pin)


@pytest.mark.parametrize("pin", ["123456", "012345678", "987654", "543210"])
def test_straight_runs_are_refused(pin: str) -> None:
    with pytest.raises(InvalidPinError, match="straight run"):
        validate_pin(pin)


def test_errors_never_repeat_the_pin() -> None:
    with pytest.raises(InvalidPinError) as error:
        validate_pin("4829")
    assert "4829" not in str(error.value)


# ── Hashing and checking ────────────────────────────────────────────────


def test_a_hash_matches_its_own_pin_only() -> None:
    pin_hash = hash_pin("482913")

    assert pin_hash.startswith("$argon2id$")
    assert "482913" not in pin_hash
    assert pin_matches(pin_hash, "482913")
    assert not pin_matches(pin_hash, "482914")
    assert not pin_matches(pin_hash, "")


def test_the_same_pin_hashes_differently_each_time() -> None:
    assert hash_pin("482913") != hash_pin("482913")


def test_hashing_applies_the_format_rules() -> None:
    with pytest.raises(InvalidPinError):
        hash_pin("123456")


def test_a_stored_value_that_is_not_a_hash_raises() -> None:
    with pytest.raises(InvalidHashError):
        pin_matches("not a hash", "482913")


# ── Rehashing ───────────────────────────────────────────────────────────


def test_a_current_hash_needs_no_rehash() -> None:
    assert not needs_rehash(hash_pin("482913"))


def test_a_rehash_is_current_and_skips_the_format_rules() -> None:
    # "111111" breaks today's rules but may predate them.
    pin_hash = rehash_pin("111111")

    assert pin_matches(pin_hash, "111111")
    assert not needs_rehash(pin_hash)


def test_a_hash_with_weaker_parameters_needs_a_rehash() -> None:
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8192).hash("482913")

    assert pin_matches(weak_hash, "482913")
    assert needs_rehash(weak_hash)
