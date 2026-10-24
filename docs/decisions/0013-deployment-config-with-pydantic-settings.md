# 0013. Load deployment config with pydantic-settings, validated at startup

- Status: Accepted
- Date: 2026-10-24

## Context
Both apps need deployment config that whoever installs the system sets once: the database path, the timezone, the public hostname and the environment mode (dev/prod). Decision [0006](0006-one-installation-per-gym.md) says everything installation-specific comes from settings (`.env` and the `settings` table), not code. This config is not one of the libraries chosen in [0003](0003-stack-additions.md), so the way it's loaded needs its own decision.

## Options
- **pydantic-settings**: typed fields read from environment variables and an optional `.env` file, validated by pydantic. Pros: the standard choice for FastAPI. It builds on pydantic, which FastAPI already installs, so it adds one small package. Cons: one more dependency.
- **python-dotenv + a hand-written dataclass**: Pros: very small. Cons: we write and test the type conversion and validation ourselves.
- **Plain `os.environ`**: Pros: no dependency. Cons: no `.env` support and all the parsing by hand.

## Decision
Use **pydantic-settings**. All deployment config lives in one settings class in `app/core/config.py`. Both apps reach it through one cached accessor, and nothing else reads `os.environ` directly. The config is **validated at startup**: a missing or invalid value stops the app with a clear error instead of letting it run on a wrong value.

## Consequences
- A typo in `.env` stops the app at startup. That's deliberate, but whoever deploys it has to read the error.
- `.env.example` (committed, made-up values) lists every key, and a test checks it matches the settings class.
- Secrets aren't part of this yet. Where the SMTP password and encryption keys live still depends on the hosting decision.
- Manager-editable values (gym name, emails, lock-screen minutes) belong in the `settings` table, not here (see [0014](0014-settings-table-after-database-foundation.md)).
