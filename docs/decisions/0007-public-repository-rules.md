# 0007. Public repository: no secrets, no real data, Claude files included

- Status: Accepted
- Date: 2026-10-14

## Context
The code will be in a public GitHub repo as a portfolio project, while the system itself handles real customers' personal and health data. We needed rules so that nothing sensitive ever gets published, and a decision on whether the Claude Code files belong in the repo.

## Options
- **Private repo**: no risk of leaks, but nothing to show employers.
- **Public repo, relying on care and `.gitignore`**: works until someone makes one mistake, such as a key typed into the code.
- **Public repo with layered protection**: `.gitignore` for data and secret files, secrets only from environment variables, and an automatic scanner that blocks commits containing secrets.

For the Claude files: hide them, or publish them to show how the project was built with AI.

## Decision
A public repo with layered protection:
- **Real customer data lives only in the database**, never in the repo: not in tests, fixtures, examples or screenshots. Tests use made-up data.
- **Secrets come only from environment variables or a secret store**, never from code. `.env` is ignored; `.env.example` (no real values) is committed.
- `.gitignore` excludes the database, reports, backups, uploads, logs, `.env` files, keys and certificates.
- **gitleaks** scans for secrets, as a pre-commit hook and in CI, set up in milestone 1. GitHub's secret scanning is a second layer.
- **Commits use GitHub's private noreply email** (`<id>+<username>@users.noreply.github.com`), not a personal address, to keep it out of the public history and away from spam bots. "Keep my email address private" is on in GitHub.
- **Claude files are public:** `CLAUDE.md`, `.claude/skills/` and `.claude/settings.json` show the working rules and workflow. `.claude/settings.local.json` (personal settings) is ignored.

## Consequences
- If a secret is ever pushed, deleting it isn't enough, because it stays in git history. It must be treated as leaked and replaced (rotated) immediately.
- Gym-specific values stay out of the code (see [0006](0006-one-installation-per-gym.md)).
- The README should mention that the project was built with Claude Code and point to `CLAUDE.md`.
