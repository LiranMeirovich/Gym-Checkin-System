---
name: start-feature
description: Start a new feature or milestone step. Reads the design doc, creates a branch, breaks the work into small steps, and asks which steps the developer wants to write themselves.
argument-hint: "<feature or milestone, e.g. 'milestone 1: staff accounts'>"
disable-model-invocation: true
---

# Start a feature

Feature: $ARGUMENTS

## 1. Understand it
- Read the relevant sections of the design doc (`Gym Check-In & Subscription System — Design Doc.md`) and of CLAUDE.md. Check `docs/decisions/` for any decision that applies.
- Look at the existing code this feature touches.
- If the feature is unclear, contradicts the design doc, or depends on an open question in the doc, stop and ask before planning.

## 2. Plan it
Present a short plan:
- **Goal:** one sentence.
- **Steps:** 3–8 small steps, each a reviewable change (roughly one commit each). For each step, list the files it touches and how it will be tested.
- **Protected areas:** flag any step that touches a protected area from CLAUDE.md (auth, cookie/linking, plan/price/report logic, schema).
- **Decisions needed:** any library, schema or route choice that needs the developer's call, with a recommendation.
- **Learning picks:** suggest 1–2 steps that would be good for the developer to write themselves (core logic, small and well-tested), and say why.

Then ask:
1. Does the plan look right?
2. Which steps do you want to write yourself (hint mode)?

Don't write any code until the developer answers.

## 3. Set up
After approval:
- Make sure the working tree is clean. If it isn't, ask what to do.
- Create the branch from `main`: `feature/<short-kebab-name>` (or `fix/...` for a bug fix).
- Track the steps in a todo list, marking which ones are the developer's.

## 4. Work through the steps
- **Claude's steps:** implement one step at a time, run the tests and ruff, then briefly explain the change (as in `/explain-changes`) and wait for the developer to review it before moving on.
- **Developer's steps (hint mode):** don't write the solution. Explain what's needed, point to the relevant files and docs, and review their code when they're done.
- **Commit after each reviewed step.** Once the developer is happy with a step, suggest a Conventional Commit message for it. Committing stays their call: never commit without being asked.
- If a significant technical decision comes up, suggest recording it with `/decision`.
- When all steps are done and committed, tell the developer to run `/finish-feature`.
