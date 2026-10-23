# 0012. Claude builds, the developer supervises

- Status: Accepted
- Date: 2026-10-23

## Context
The original workflow had the developer understand every line of the codebase: Claude explained each change line by line, ended walkthroughs with quiz questions, and each feature plan picked steps for the developer to write themselves in "hint mode". In practice the developer wants to spend their time on the architecture and the decisions, not on writing or studying individual lines.

## Options
- **Keep the learning workflow**: the developer writes some steps and reviews all code line by line. Pros: deep knowledge of every line. Cons: slow, and the developer's attention goes to code details instead of design.
- **Claude builds, the developer supervises**: Claude writes all the code; the developer approves architecture-level plans, makes every architectural and product decision, and reviews changes through architecture-level summaries. Pros: faster, and the discussion stays on components, data flow, contracts and trade-offs. Cons: the developer knows less of the low-level code, so the checks (tests, CI, `/code-review`, the hard rules) carry more of the weight.

## Decision
Claude builds, the developer supervises. Hint mode and the quiz questions are removed. Plans and summaries describe components, responsibilities, data flow, contracts and risks, with code shown only when it carries a decision.

## Consequences
- CLAUDE.md, `/start-feature`, `/explain-changes` and `/finish-feature` are updated to match.
- Unchanged: architectural decisions, protected areas, schema changes and new libraries still need the developer's OK; commits and pushes still happen only when asked; one feature = one branch = one session.
- Summaries must flag anything risky or hard to undo, since the developer won't be reading every line.
