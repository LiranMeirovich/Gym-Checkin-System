---
name: finish-feature
description: Wrap up a finished feature branch. Checks the whole branch (tests, lint, secrets, code review), fixes what comes up, updates the project status in CLAUDE.md, opens the pull request and, on the developer's OK, merges it into main once CI is green.
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
- Fix the ones the developer approves, one at a time, with a one-line summary of each fix. A fix in a protected area needs the developer's OK first.
- Re-run the checks that failed until they pass.

## 4. Update the project status
Update the **Project status** section of CLAUDE.md so the next session (which won't remember this one) knows where things stand:
- Add this feature to the **Done** line: its name and decision number only, no details (git history and the decision record hold those).
- Add any new core module the next features will use to **Key modules**.
- Update the current milestone and the next feature to build.

CLAUDE.md is loaded into every session, so keep it short: replace outdated lines instead of adding new ones. Also update the **Commands** section if this feature added any.

Update `docs/follow-ups.md`: add follow-ups found during this feature that weren't done, under the milestone they're due in, and remove the ones this feature finished.

Suggest `/decision` for any significant technical choice made during the feature that has no record yet.

## 5. Prepare the commit and pull request
- Suggest a Conventional Commit message for the wrap-up changes (review fixes and the status update). Don't commit unless the developer asks.
- Draft the pull request description:
  - **What:** what the feature does, in 2–4 bullets.
  - **Why:** the design-doc section or decision it implements.
  - **How it was tested:** tests added, manual checks.
  - **Notes:** follow-ups, known limits, anything a reviewer should look at closely.
- If the repo has a GitHub remote, offer to push the branch and open the PR (only after the developer agrees). If not, give them the description to use later.
- **After the push, give a quick summary of what the feature added**, so the developer can judge it before deciding to merge. Keep it to about 5–8 bullets, at the architecture level (no code), based on `git diff --stat main...HEAD` and the branch's commits:
  - **What it does now:** the new behaviour, from the staff's or customer's side, in a line or two.
  - **Components:** modules, tables, routes, templates or jobs added or changed, each with what it's responsible for.
  - **Contracts and data:** new migrations, settings or `.env` keys, route contracts, and new dependencies.
  - **Decisions:** decision records added in this branch.
  - **Left out:** follow-ups and known limits.
  - The PR link.

## 6. Merge into main
Only after the PR is open, and only when the developer says to merge. Ask once: "Merge into main?"
- **CI must be green.** Check the PR's checks once with `gh pr checks <number>`. If any are pending, stop and say so (don't poll or wait in a loop); the developer can ask again once they finish. If any failed, report which, and fix them like the findings in step 3 before merging. `main` has no branch protection yet, so this check is the only thing that stops a red PR going in.
- **Merge** with a merge commit, as the earlier PRs were: `gh pr merge <number> --merge --delete-branch`.
- **Tidy up:** switch to `main`, `git pull`, and delete the local feature branch (`git branch -d <branch>`). If `main` is checked out in another worktree, or the working tree isn't clean, skip the switch and tell the developer instead of forcing it.
- If the merge fails (conflicts, a check turned red), stop and report it. Never force-merge or use `--admin`.

## 7. Close out
End with a short summary: checks passed, what was fixed, whether the PR was merged, what's left as a follow-up, and the next feature. Remind the developer that the next feature should start in a **new session** with `/start-feature`.
