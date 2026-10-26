# 0020. React + TypeScript frontend with a JSON API

- Status: Accepted (supersedes the frontend part of [0003](0003-stack-additions.md))
- Date: 2026-10-26

## Context
[0003](0003-stack-additions.md) chose server-rendered Jinja2 templates + HTMX, with no build step. The project is also a portfolio piece, and the developer wants to show a modern frontend: a React app talking to a JSON API, which is what employers look for. Milestone 1 has built almost no screens yet (setup, login and a placeholder home), so this is the cheapest point to switch. After milestones 3 and 4 it would mean rewriting every screen.

## Options
- **Keep Jinja2 + HTMX**: one language, no build step, less to secure. Cons: weaker as a portfolio piece; the server-rendered pages aren't reusable by any other client.
- **React + TypeScript single-page apps, JSON API, served by FastAPI from the same domain**: standard and marketable, typed end to end. Cons: two languages, a Node toolchain in development and CI, and every screen needs both an API route and a component.
- **A separate frontend server (Next.js or similar)**: server-side rendering. Cons: a Node server running in production on the gym PC, and a second origin to secure; nothing here needs it.

## Decision
React + TypeScript, built with Vite, served as static files by the FastAPI apps from the same domain:
- **Backend:** routes in `app/admin` and `app/public` return JSON under `/api/...`, with Pydantic request and response schemas. Routes stay thin: they check permissions, call `app/core` and return its result. Business logic lives only in `app/core`, which this decision doesn't change.
- **Frontend:** one Vite project in `frontend/` with **two separate builds**, admin and public. The public build never contains admin screens or admin API calls, which extends "never register admin routes on the public app" to the browser code.
- **Typed API:** TypeScript types are generated from FastAPI's OpenAPI spec (`openapi-typescript`), so a backend change that breaks the frontend fails at compile time.
- **Data fetching:** TanStack Query, including timed refetching for the live dashboard.
- **Logins unchanged:** the staff session and the `gym_device` cookie stay server-set `HttpOnly` cookies. React never reads or stores a token (no `localStorage`, `sessionStorage` or IndexedDB).
- **Runtime:** in development, the Vite dev server proxies `/api` to FastAPI. In production, FastAPI serves the built files, so the host needs no Node at runtime, only at build time.
- **Styling:** chosen in milestone 4 with the `frontend-design` skill. It must handle Hebrew right-to-left ([0002](0002-hebrew-rtl-user-interface.md)).

## Consequences
- A new feature, **frontend foundation**, comes right after the activity log at the end of milestone 1. It sets up the Vite project, both builds, serving from FastAPI, type generation and CI, and rebuilds setup, login and home in React. Jinja2 and the templates are removed once nothing uses them.
- The CSRF and auto-lock parts of [0019](0019-staff-sessions-csrf-and-lock-times.md) move to the React side. The origin check stays as it is. The signed token is sent by `fetch` as the `X-CSRF-Token` header instead of a hidden form field, and the auto-lock timer runs in React. The frontend foundation feature decides how the token reaches the page.
- Every protected JSON route still declares `CurrentStaff` or `require_permission`. Hiding something in React is never the protection.
- CI gains a Node job (install, type-check, lint, build). The host's build or deploy step (milestone 6) must produce the frontend files before the apps start.
- Each screen now costs an API route plus a component, and the project needs Node as well as uv in development.
