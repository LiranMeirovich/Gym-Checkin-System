# Decision records

One line per decision: what it settled, and when to read it. Read the full record only when the feature touches that area. `/decision` adds a line here for every new record.

| # | Decision | Read when |
| --- | --- | --- |
| [0001](0001-use-fastapi-for-the-backend.md) | FastAPI for the backend | changing the backend framework |
| [0002](0002-hebrew-rtl-user-interface.md) | Hebrew, right-to-left UI; code and docs in English | any UI text or layout |
| [0003](0003-stack-additions.md) | SQLAlchemy, Alembic, uv, ruff, pytest, CI (its Jinja2 + HTMX part is superseded by 0020) | adding to the stack |
| [0004](0004-health-form-blocks-check-in.md) | A valid health form is required for every check-in | health form, check-in (milestone 3) |
| [0005](0005-encrypt-the-database-with-sqlcipher.md) | SQLCipher encrypts the whole DB file; no field-level encryption | storage, encryption, backups |
| [0006](0006-one-installation-per-gym.md) | One installation per gym; nothing gym-specific in code | anything gym-specific (name, prices, emails) |
| [0007](0007-public-repository-rules.md) | Public repo: no secrets, no real data | tests, fixtures, examples, secrets |
| [0008](0008-split-milestone-1-into-features.md) | Milestone 1 split into features | history only |
| [0009](0009-health-route-on-both-apps.md) | `GET /health` on both apps | health checks, monitoring |
| [0010](0010-add-dependencies-when-needed.md) | Add each dependency in the feature that first uses it | adding a library |
| [0011](0011-code-quality-and-supply-chain-tooling.md) | Ruff rules, pre-commit hooks, SHA-pinned actions | lint rules, hooks, CI |
| [0012](0012-claude-builds-developer-supervises.md) | Claude builds, the developer supervises | workflow |
| [0013](0013-deployment-config-with-pydantic-settings.md) | Deployment config via pydantic-settings, validated at startup | adding a `.env` key or secret |
| [0014](0014-settings-table-after-database-foundation.md) | Settings table built after the database foundation | history only |
| [0015](0015-database-access-and-migration-conventions.md) | DB sessions, migrations, FK handling, UTC timestamps | any schema change, DB access, timestamps |
| [0016](0016-gym-settings-in-a-key-value-table.md) | Gym settings in a key/value table, defined in code | adding a manager-editable setting |
| [0017](0017-instructors-never-choose-plans.md) | Instructors never choose plans; their check-in falls back to single entry | plans, manual check-in |
| [0018](0018-staff-pins-and-the-permission-map.md) | Argon2id PINs, lockout, one permission map | staff auth, permissions |
| [0019](0019-staff-sessions-csrf-and-lock-times.md) | Server-side staff sessions, CSRF, lock times | admin auth, any admin POST route |
| [0020](0020-react-typescript-frontend-with-a-json-api.md) | React + TypeScript frontend, JSON API, two builds | any screen or API route |
| [0021](0021-append-only-activity-log-and-no-customer-deletion.md) | Append-only activity log; customers never deleted | any feature that changes data |
| [0022](0022-split-milestone-2-into-features.md) | Milestone 2 split into four features, no freezes | milestone 2 features |
| [0023](0023-customer-identity-phone-and-active-flag.md) | One customer per phone (E.164, Israeli rules), `active` flag instead of `archived_at`, date of birth required | customers, phone numbers, phone linking |
