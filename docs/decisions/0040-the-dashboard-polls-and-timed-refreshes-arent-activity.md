# 0040. The dashboard polls, and timed refreshes don't count as activity

- Status: Accepted
- Date: 2026-11-09

## Context
The dashboard is milestone 4's last feature (decision 0037): today's check-ins "live", health forms waiting for a doctor's note, forms expiring in the next 30 days, and the newest customers. The instructor at the desk watches it to spot a check-in or sign-up that doesn't match who is in the gym (design doc, "Fake check-ins").

The lists must update without anyone touching the screen. The staff session locks after a stretch with no activity, and every request counts as activity on the server (`touch()` in `_current_staff`) and in React's lock timer (`session.tsx`). A screen that refreshes itself would keep the session open forever. Decision 0037 left the fix to this feature, along with letting the customer page's phone list refresh while a link code is on screen.

## Options
- **Updates**: WebSockets or server-sent events (instant, but a long-lived connection, more server code and a single-worker uvicorn holding it open), or polling on a timer (plain GETs through the existing routes, at most a few seconds late).
- **Routes**: one dashboard route returning all four lists (one request, but a screen-shaped contract nothing else can reuse), or four list routes (each reusable, each refreshing at its own pace and hidden by its own permission).
- **Not counting refreshes as activity**: a separate unauthenticated refresh route (would bypass the permission checks), a header on the request that the server and React both honour, or React's timer only (the server would still keep the session alive).
- **Which requests carry the header**: every fetch of a polled query (TanStack Query's `refetchInterval` can't tell them apart), or only the fetches the timer sends.
- **How a check-in was made** (phone or desk): shown on the lists, or not shown.

## Decision
- **Polling, not sockets.** Today's check-ins refresh every 15 seconds, the other lists every minute; refreshing waits while the window is hidden.
- **Four GET routes**: `/api/checkins/today` and `/api/customers/latest` (`customers.view`), `/api/health-forms/needing-note` and `/api/health-forms/expiring` (`health_forms.view_status`). An instructor sees the form lists too, since they show only valid / not valid and dates (decision 0004's split holds).
- **`X-Background-Refresh: 1` marks a refresh**: on a GET, `_current_staff` checks the session as usual but skips `touch()`; `session.tsx` doesn't reset its lock timer for it. The header can only give up activity, never grant access.
- **Only the timer's fetches carry it** (`usePolledQuery` in `frontend/src/admin/polling.ts`). The first load, coming back to a screen, returning to the window and a reload after a failed save are a person's doing and count as activity.
- **The phone list polls every 4 seconds only while a link code shows** and stops when a new phone appears (the code is hidden) or the code expires. A code is issued only after the list has loaded, so "new" is known.
- **No phone/desk marking** on the dashboard or the customer page's check-ins. The `method` column stays in the table for reports; the instructor recognises people, not methods.
- Today's date for these lists is the gym's (`local_today()` in `app/core/clock.py`).
- `checkins.checked_in_at` gets an index, for today's and a month's visits.

## Consequences
- An idle dashboard locks on time, and a refresh after the session expired is a 401 that sends the screen to the lock screen like any other.
- A check-in shows on the dashboard up to 15 seconds late. Sockets can replace polling later behind the same routes.
- Every refresh still opens a `BEGIN IMMEDIATE` transaction and takes the write lock briefly (follow-up).
- Any future screen that refreshes itself must use `usePolledQuery`, or it will keep sessions alive.
- The phone list has no manual Refresh button any more (follow-up).
- The report and backup cards come with milestones 5 and 6.
