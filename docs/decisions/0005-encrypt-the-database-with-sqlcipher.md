# 0005. Encrypt the whole database with SQLCipher

- Status: Accepted
- Date: 2026-10-14

## Context
The original design didn't encrypt customer data, because the key would sit on the same PC, BitLocker already covered a stolen disk, and encrypting fields would break name search. Two things changed: the system now stores health forms ([0004](0004-health-form-blocks-check-in.md)), and it will probably run on a server whose disks someone else controls.

## Options
- **No encryption**: simplest, but the database file or a disk snapshot would expose health data if it ever leaked.
- **Field-level encryption** (encrypt names, phones and health answers one by one): breaks name search, needs extra tricks to look customers up by phone, and touches all the code. The key still lives on the same machine.
- **Whole-database encryption (SQLCipher)**: the entire SQLite file is encrypted. Queries and search work as usual. It's mostly a different driver plus a key at startup.

## Decision
SQLCipher, whatever hosting is chosen. Field-level encryption is still rejected.

## Consequences
- **It protects against** the database file, a disk snapshot or an old disk leaking on its own.
- **It doesn't protect against** someone with full (root) access to the running machine, or an attacker getting in through the app itself. Those depend on who has access to the host, and on securing the app (authentication, CSRF protection, rate limiting, updates).
- The key must be kept outside the database and backed up off the machine. Without it, the data can't be read.
- SQLCipher is easy to install on Linux/Docker and harder on Windows, so it's added in milestone 6. Until then development uses plain SQLite, and the switch is mostly a connection-string change.
