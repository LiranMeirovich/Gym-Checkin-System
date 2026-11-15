# 0048. SQLCipher through `sqlcipher3`, a raw key, plain in dev without one

- Status: Accepted
- Date: 2026-11-15

## Context
Decision 0005 chose SQLCipher to encrypt the whole database file, and left the driver, the key and the dev setup to milestone 6 (decision 0047, feature 1). It expected SQLCipher to be hard to install on Windows, where development happens. Production runs on a Linux server (decision 0046).

## Options
**Driver**
- **`sqlcipher3`** (the original maintainer's package, MIT): wheels with SQLCipher and OpenSSL built in, for Windows and for Linux (`manylinux_2_28`, x86_64 and aarch64).
- **`sqlcipher3-wheels`**: a community fork with similar wheels, released less often.
- **`pysqlcipher3`**: abandoned.

**How the engine gives the key**
- **SQLAlchemy's `sqlite+pysqlcipher` dialect**: the key goes in the URL's password.
- **The ordinary `sqlite` dialect with `module=sqlcipher3`**, and our connect listener running `PRAGMA key` first.

**Key format**
- **A passphrase**: SQLCipher stretches it with about 256,000 PBKDF2 rounds on every new connection.
- **A raw 256-bit key** (64 hex digits, `x'...'`): used as it is, no stretching.

**Dev without a key**
- **Required everywhere.**
- **Optional in dev**: no key means a plain SQLite file.

## Decision
- **Driver:** `sqlcipher3`. It installs from a wheel on both Windows and Linux, so dev uses the same driver as prod; Python's `sqlite3` isn't used any more.
- **Engine:** the ordinary `sqlite` dialect with `module=sqlcipher3`. The key never sits in a URL, a repr or a log line, and the existing pragmas and transactions (decisions 0015, 0027) are unchanged.
- **Key:** `GYM_DATABASE_KEY`, a raw 256-bit key as 64 hex digits, required in prod. Because `PRAGMA key` takes no bound parameters, the key goes into the SQL text, so it is checked as hex-only both in `config.py` and in `app.core.db.raw_key()`.
- **Dev:** without a key the file is plain SQLite, so dev databases (and demo data) open in ordinary tools. The test suite still sets a key for every test, so the encrypted path is the one tested.
- **Startup:** both apps and `alembic` refuse a key that can't open the file, naming which of three problems it is: a plain file with a key, an encrypted file without one, or a wrong key.
- **Conversion:** `python -m app.encrypt_database` encrypts an existing plain database once, with both apps stopped. It checks the copy before swapping, and renames the plain original to `<name>.plain-<date>` rather than deleting it: deleting is irreversible, and the conversion runs once, by hand.

## Consequences
- **Losing the key loses the data,** backups made from the encrypted file included. It goes on the "keys to keep off the machine" list.
- **The server needs glibc 2.28 or newer** for the Linux wheels: Debian 10+, Ubuntu 20.04+, RHEL 8+.
- **OpenSSL is bundled in the wheel,** so its security fixes arrive only with new `sqlcipher3` releases; `uv.lock` pins the wheel's hashes.
- **The driver's SQLite is its own** (3.54.1 with SQLCipher 4.20.0 when this was written), not Python's. The full test suite runs on it.
- **The driver's exceptions** are `sqlcipher3.dbapi2.*`, not `sqlite3.*`. Code catches SQLAlchemy's exceptions, so only raw-driver code (tests, the conversion command, the startup check) uses the driver's module.
- **Backups (feature 2)** copy an encrypted database. A copy made with the key stays encrypted with the same key.
- **No key rotation** (`PRAGMA rekey`) or decrypt command yet.
