---
name: decision
description: Record a technical decision as a short decision record (ADR) in docs/decisions/. Use when the user asks to record or document a decision, or after a significant technical choice is made (a library, the hosting, a schema design, a security approach).
argument-hint: "<the decision, e.g. 'use FastAPI over Django'>"
---

# Record a decision

Decision: $ARGUMENTS

## 1. Gather the facts
- Use what was discussed in this conversation. If the context, options or reasons are unclear, ask the developer. Don't invent reasons they didn't give.
- Check `docs/decisions/` for an earlier record on the same topic. If this decision replaces one, mark the old one's status as `Superseded by NNNN` and link it.

## 2. Write the record
File: `docs/decisions/NNNN-short-kebab-title.md`, where `NNNN` is the next number (start at `0001`).

```markdown
# NNNN. <Title as a short statement, e.g. "Use FastAPI for the backend">

- Status: Accepted
- Date: YYYY-MM-DD

## Context
What problem or question led to this decision, and which constraints matter (from the design doc, the gym, the budget, security).

## Options
- **Option A**: one line on how it works. Pros / cons.
- **Option B**: ...

## Decision
What was chosen, and the main reasons why.

## Consequences
What this makes easier, what it makes harder, and anything we now have to do because of it.
```

Keep it short: under a page. Write it in English, in plain language the developer could explain in an interview.

## 3. Follow up
- Add a line for the new record to the index `docs/decisions/README.md` (number, what it settled, when to read it). If it supersedes one, note that on the old record's line.
- If the decision changes the stack, a hard rule or a convention, update CLAUDE.md to match and say what you changed.
- If it contradicts the design doc, point that out and suggest the edit to the doc. Don't edit the design doc without asking.
