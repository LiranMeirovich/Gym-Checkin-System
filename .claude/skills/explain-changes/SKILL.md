---
name: explain-changes
description: Walk the developer through recent code changes so they fully understand them, then check their understanding with a few questions. Use when the user asks to explain a diff, commit, branch or file, or says "walk me through this".
argument-hint: "[commit | branch | file path] (default: uncommitted changes)"
---

# Explain changes

The developer must understand every part of this codebase (see CLAUDE.md). Your job here is to teach, not to summarize.

## 1. Find what to explain
- With an argument: explain that commit, branch (compared to `main`) or file.
- Without one: explain the uncommitted changes (`git diff` and `git diff --staged`, plus new untracked files). If there are none, explain the last commit.
- If the change is large, list the files first and explain them in a sensible order (data model → core logic → routes → templates → tests), not alphabetically.

## 2. Explain it
For each meaningful piece:
- **What it does**, in plain words, with a short excerpt of the key lines (`path:line`). Don't paste whole files.
- **Why it's built this way**: the design-doc rule, decision record or constraint behind it. If there was a reasonable alternative, name it and say why it wasn't used.
- **New concepts**: explain any Python, FastAPI, SQLAlchemy, HTMX or security idea the developer may not know yet (for example dependency injection, a context manager, CSRF, password hashing), in 2–4 sentences.
- **How it connects**: what calls this code, and what it calls.

Skip trivial lines (imports, formatting). Point out anything risky or surprising instead of hiding it.

## 3. Check understanding
End with 2–3 short questions the developer should be able to answer about the change, such as "what happens if a customer scans twice within 10 minutes?" or "why is the token hashed before it's stored?". Don't give the answers unless asked. If they answer, say what's right and correct what's wrong.

## Style
- Match the developer's level: assume they know basic Python and web concepts, but not this framework's details.
- Be concrete and short. A good explanation is one they could repeat in a job interview.
