"""Staff PINs: the format rules, hashing and checking (design doc: "Staff
login and lock screen"; decision 0018).

PINs are stored only as Argon2id hashes. This is the one module that uses
the hashing library, so its parameters and any later change of algorithm
stay in one place. Nothing here ever puts a PIN or a hash in an error
message: they end up in logs.
"""

import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

PIN_MIN_LENGTH = 6
PIN_MAX_LENGTH = 12

# ASCII digits only. str.isdigit() and \d also accept other scripts' digits
# ("٠١٢٣٤٥"), which look different on every keyboard and screen.
_PIN = re.compile(rf"[0-9]{{{PIN_MIN_LENGTH},{PIN_MAX_LENGTH}}}")

# argon2-cffi's defaults (RFC 9106's low-memory profile). needs_rehash()
# compares stored hashes against these, so raising them later upgrades each
# PIN at its owner's next login.
_hasher = PasswordHasher()


class InvalidPinError(ValueError):
    """A new PIN breaks the format rules. The message says which rule, never
    the PIN itself."""


def validate_pin(pin: str) -> None:
    """Refuse a PIN that can't be set: wrong length, anything but ASCII
    digits, one digit repeated ("000000"), or a straight run up or down
    ("123456", "987654"), the PINs people try first."""
    if not isinstance(pin, str) or not _PIN.fullmatch(pin):
        raise InvalidPinError(
            f"a PIN is {PIN_MIN_LENGTH} to {PIN_MAX_LENGTH} digits (0-9)"
        )
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:], strict=False)}
    if steps == {0}:
        raise InvalidPinError("a PIN can't be one digit repeated")
    if steps in ({1}, {-1}):
        raise InvalidPinError("a PIN can't be a straight run of digits")


def hash_pin(pin: str) -> str:
    """Check ``pin`` against the format rules and return its hash, for
    storing. Raises ``InvalidPinError`` if it breaks a rule."""
    validate_pin(pin)
    return _hasher.hash(pin)


def rehash_pin(pin: str) -> str:
    """A fresh hash of a PIN that just matched its old hash (see
    ``needs_rehash``). The format rules aren't applied: a PIN set under
    older rules must keep working."""
    return _hasher.hash(pin)


def pin_matches(pin_hash: str, pin: str) -> bool:
    """Whether ``pin`` is the PIN behind ``pin_hash``.

    The format rules aren't applied here: a wrong-looking entry is simply
    a wrong PIN. A stored hash that isn't an Argon2 hash at all raises
    (``argon2.exceptions.InvalidHashError``) instead of reading as a wrong
    PIN, so broken data is noticed.
    """
    try:
        return _hasher.verify(pin_hash, pin)
    except VerifyMismatchError:
        return False


def needs_rehash(pin_hash: str) -> bool:
    """Whether ``pin_hash`` was made with weaker or different parameters
    than the current ones, and should be replaced after a correct PIN."""
    return _hasher.check_needs_rehash(pin_hash)
