---
name: explain-changes
description: Walk the developer through recent changes at the architecture level: which components changed, how they fit together, the decisions behind them and the risks. Use when the user asks to explain a diff, commit, branch or file, or says "walk me through this".
argument-hint: "[commit | branch | file path] (default: uncommitted changes)"
---

# Explain changes

Claude writes the code and the developer supervises it (see CLAUDE.md, decision 0012). Your job here is to give them what they need to judge the change as its architect, not a line-by-line tour.

## 1. Find what to explain
- With an argument: explain that commit, branch (compared to `main`) or file.
- Without one: explain the uncommitted changes (`git diff` and `git diff --staged`, plus new untracked files). If there are none, explain the last commit.

## 2. Explain it
- **The shape of the change:** which components (modules, tables, routes, templates, jobs) were added or changed, and what each is responsible for. Group by component, not by file.
- **How it fits:** how data and requests flow through the change, which app (admin or public) it lives in, and what it depends on or is depended on by. A small text diagram helps when there's a flow.
- **Contracts:** any new or changed table, route, setting or interface between components, in outline. Show a short snippet only when the exact shape is the decision (a schema, a route signature, a security check).
- **Why it's built this way:** the design-doc rule, decision record or constraint behind it. If there was a reasonable alternative, name it and say why it wasn't used.
- **Risks:** anything security-relevant, hard to undo, surprising, or diverging from the design doc or the plan. Don't hide it.
- **Tests:** what is covered and what isn't, in a line or two.

## Style
- Be concrete and short. Skip implementation details that don't affect the architecture.
- End by naming any decision the developer still needs to make about this change, if there is one.
