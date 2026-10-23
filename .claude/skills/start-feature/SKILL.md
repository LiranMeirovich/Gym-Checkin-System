---
name: start-feature
description: Start a new feature or milestone step. Reads the design doc, presents an architecture-level plan for the developer to approve, creates a branch, and builds the feature step by step.
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
Present a short plan, written at the architecture level:
- **Goal:** one sentence.
- **Architecture:** the components this feature adds or changes, what each is responsible for, how data flows between them (and between the admin and public apps), and where each sits in the layout (`app/core`, `app/admin`, `app/public`). Outline any new tables or route contracts.
- **Steps:** 3–8 small steps, each a reviewable change (roughly one commit each). For each step, one line on what it delivers and how it will be tested.
- **Protected areas:** flag any step that touches a protected area from CLAUDE.md (auth, cookie/linking, plan/price/report logic, schema).
- **Decisions needed:** any library, schema or route choice that needs the developer's call, with options and a recommendation.
- **Risks and trade-offs:** what could go wrong or be hard to change later, and what this feature deliberately leaves out.

Then ask whether the plan looks right, and get an answer on each decision. Don't write any code until the developer approves.

## 3. Set up
After approval:
- Make sure the working tree is clean. If it isn't, ask what to do.
- Create the branch from `main`: `feature/<short-kebab-name>` (or `fix/...` for a bug fix).
- Track the steps in a todo list.

## 4. Work through the steps
- Implement one step at a time, and run the tests and ruff.
- After each step, give a short architecture-level summary: what it adds, how it fits with the rest, any deviation from the plan, and anything risky. No line-by-line code walkthrough.
- If a step turns up a decision that wasn't in the plan (library, schema, route contract, folder structure, protected area), stop and ask before going on.
- **Commit after each approved step.** Once the developer is happy with a step, suggest a Conventional Commit message for it. Committing stays their call: never commit without being asked.
- If a significant technical decision comes up, suggest recording it with `/decision`.
- When all steps are done and committed, tell the developer to run `/finish-feature`.
