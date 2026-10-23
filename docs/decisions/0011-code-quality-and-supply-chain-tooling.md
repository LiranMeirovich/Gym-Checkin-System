# 0011. Code-quality and supply-chain tooling

- Status: Accepted
- Date: 2026-10-23

## Context
Decision [0003](0003-stack-additions.md) chose ruff, pytest and GitHub Actions, and [0007](0007-public-repository-rules.md) chose gitleaks as a pre-commit hook and in CI. The project-setup feature had to decide how to configure and run them: which lint rules, how the commit hooks are installed, and how far to trust third-party code that runs in CI. The repo is public and the system will hold health data, so security checks and supply-chain safety matter.

## Options
**Lint rules**
- **Ruff's defaults only** (`E4, E7, E9, F`): unused imports, undefined names, syntax errors. Nothing for security.
- **Defaults plus `I`, `B`, `UP`, `SIM` and `S`**: adds import order, likely bugs, modern syntax, simplifications and security checks (bandit). Cons: the occasional false alarm, silenced per line with `# noqa`.

**Commit hooks**
- **A hand-written script in `.git/hooks/`**: no extra tool, but `.git/` isn't committed, so the hook exists only on one machine.
- **The `pre-commit` framework**: hooks listed in a committed `.pre-commit-config.yaml`; any clone gets the same hooks with `pre-commit install`.
- For ruff inside it: the **`ruff-pre-commit` hook** (its own copy of ruff, with its own version) or a **local hook running `uv run --locked ruff`** (the version locked in `uv.lock`).

**Third-party code in CI and hooks**
- **Version tags** (`@v7`): readable and pick up fixes automatically, but a tag can be moved to different code by whoever controls the repo.
- **Full commit SHAs** (`@3d3c42e…  # v7.0.1`): can never change. Cons: no automatic updates.

## Decision
- **Ruff rules:** `E4, E7, E9, F, I, B, UP, SIM, S`. The defaults are listed explicitly because `select` replaces them. `S` catches mistakes this system is exposed to, such as hard-coded secrets or `random` instead of `secrets` for tokens and link codes. Only `S101` (`assert`) is turned off, and only in `tests/`.
- **Hooks:** the `pre-commit` framework, running gitleaks plus ruff check and ruff format (`--check`, so files are never rewritten silently). Ruff runs as a local hook through `uv run --locked`, so the hook, CI and the editor all use the one ruff version in `uv.lock`.
- **Pinning:** every GitHub Action and the gitleaks hook are pinned to a full commit SHA, with the version in a comment. This is GitHub's own recommendation for third-party actions.

## Consequences
- Every clone needs `pre-commit install` once. `git commit --no-verify` skips the hooks, so CI repeats the same checks (and the tests), where they can't be skipped.
- Security rule hits must be fixed, not silenced; a `# noqa` needs a short reason on the same line. Never write a security check as `assert` (it disappears under `python -O`).
- Pinned SHAs don't update themselves. Updating an action means finding the new release's SHA; Dependabot can do this later (milestone 6).
- CI and the format hook both check Python code blocks inside Markdown files, since this ruff version formats them.
