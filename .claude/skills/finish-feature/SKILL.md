---
name: finish-feature
description: Wrap up a finished feature branch. Checks the whole branch (tests, lint, secrets, code review), fixes what comes up, updates the project status in CLAUDE.md, and prepares the final commit and pull request.
disable-model-invocation: true
---

# Finish a feature

This runs at the end of a feature, after its steps have been built, reviewed and committed one by one (see `/start-feature`). It checks the feature as a whole before it goes into `main`.

## 1. Check the starting point
- Confirm we're on a `feature/...` or `fix/...` branch, not `main`.
- Run `git status`. If there are uncommitted changes, list them and ask whether they belong to the last step (commit them first) or should be dropped. Don't continue until the working tree is clean.
- Show what the branch contains: `git log --oneline main..HEAD` and `git diff --stat main...HEAD`.

## 2. Check the whole branch
Run each check and report the results plainly. Never hide a failure.
1. **Tests:** `uv run pytest`
2. **Lint and format:** `uv run ruff check .` and `uv run ruff format --check .`
3. **Secrets:** `gitleaks git --log-opts="main..HEAD"` (skip with a note if gitleaks isn't installed yet)
4. **Code review:** run `/code-review` on the branch.
5. **Project rules:** check the diff against the hard rules in CLAUDE.md: no real customer data, nothing gym-specific in code, no secrets, no admin routes on the public app, money in agorot, permission checks on the server, no `localStorage`.
6. **Design doc:** does the feature match the design doc? List any difference.
7. **Leftovers:** debug prints, commented-out code, TODOs without a follow-up, unused files.

## 3. Fix what came up
- Present the findings, most important first, and say which ones you suggest fixing now and which can be follow-ups.
- Fix the ones the developer approves, one at a time, and explain each fix as usual. A fix in a protected area needs the developer's OK first.
- Re-run the checks that failed until they pass.

## 4. Update the project status
Update the **Project status** section of CLAUDE.md so the next session (which won't remember this one) knows where things stand:
- What this feature finished, in one line.
- The current milestone and the next feature to build.
- Follow-ups found during this feature that weren't done.

Keep it short and replace outdated lines instead of adding new ones each time. Also update the **Commands** section if this feature added any.

Suggest `/decision` for any significant technical choice made during the feature that has no record yet.

## 5. Prepare the commit and pull request
- Suggest a Conventional Commit message for the wrap-up changes (review fixes and the status update). Don't commit unless the developer asks.
- Draft the pull request description:
  - **What:** what the feature does, in 2–4 bullets.
  - **Why:** the design-doc section or decision it implements.
  - **How it was tested:** tests added, manual checks.
  - **Notes:** follow-ups, known limits, anything a reviewer should look at closely.
- If the repo has a GitHub remote, offer to push the branch and open the PR (only after the developer agrees). If not, give them the description to use later.

## 6. Close out
End with a short summary: checks passed, what was fixed, what's left as a follow-up, and the next feature. Remind the developer that the next feature should start in a **new session** with `/start-feature`.
