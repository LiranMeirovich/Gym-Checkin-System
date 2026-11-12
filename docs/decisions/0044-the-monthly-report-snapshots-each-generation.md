# 0044. The monthly report: one row per customer, a snapshot per generation, generated outside the request lock

- Status: Accepted
- Date: 2026-11-11

## Context
Milestone 5's second feature (decision 0043) is the report: what each customer pays for a month, worked out from history, previewed on a manager-only Reports screen, and saved as Excel and PDF in `reports/`. The design doc left some questions open:
- **How it's stored:** its `reports` table was one row per month, with file paths and delivery columns.
- **Combined months:** it had no rule for a customer with two plans in one month.
- **Card end date:** its sample used a card's expiry date (1 Mar) as the end date.
- **Plan type column:** whether the report shows one was an open question.

A report can take a second or more to build, and every request holds SQLite's write lock for its whole transaction (decision 0027). Building one inside a request would hold up check-ins.

## Options
- **Preview:** a live calculation, with files written only on Regenerate, so the preview can drift from the files. Or a stored snapshot that the preview and both files come from.
- **Storage:** one row per month, updated on each regeneration. Or one append-only row per generation.
- **Where generation runs:** inside the request (simple, but it holds the write lock). Or a background task after the response, with its own short transactions.
- **Two plans in one month** (a card that ran out, then a plan): one row per charge, or one row per customer.

## Decision
**Storage**
- `reports` has one **append-only row per generation**: `month`, `generated_at`, `staff_user_id` (empty for the scheduled job) and `rows_json`, the snapshot.
- The newest row for a month is its report. The preview, the Excel file and the PDF all come from the same snapshot.
- File paths aren't stored; they follow from the month (`report-2026-11.xlsx` in `GYM_REPORTS_DIR`).
- Delivery steps (emailed, approved, sent) will be rows of their own that name a generation, not columns.

**Generation** (`app.core.report_generation`)
- `POST /api/reports/{month}/generate` claims the month and answers 202. The work runs as a background task after the response.
- The read is a plain `BEGIN` (a consistent snapshot, no write lock).
- The files are written under a `.partial` name, then moved into place.
- One short `BEGIN IMMEDIATE` transaction adds the row and logs `report.generate`.
- Only finished months can be generated, and one generation per month runs at a time. The claim lives in the process (one worker) and counts as abandoned after 10 minutes, in case its job never ran.

**Rows** (`app.core.reports.calculate()`)
- **One row per customer:** the plans in the order they were made ("Punch card + Monthly"), the payments added up, and the latest plan's end date.
- **Plan type column:** the files and the preview both have one.
- **Prices:** always the price copied onto the choice or card, never the price table.
- **Single entry** counts the month's check-ins not charged to a card.
- **A punch card** is paid in the month it was bought and ends on its last valid day, as the screens show it. Next month it gets a 0 row only if it still had entries on that month's 1st.

**Routes**
- `GET /api/reports` lists the months that can be opened: from the first month with a plan or card up to last month. The server decides, so React never works out "last month".
- **Downloads** go through the API client, so a 401 reaches the lock screen. They aren't logged.
- **Excel** is written with `openpyxl`.

## Consequences
- Past reports regenerate the same, and every generation stays on record. The files on disk are only the newest one.
- Check-ins carry on while a report builds. A failed generation shows on the screen only as "failed", with a hint to close the file if Excel has it open; the cause is in the server log.
- Feature 3 (delivery) approves a specific generation, and a regeneration after approval is a new, unapproved one. The scheduled job calls `generate(month, by=None)`.
- The Hebrew plan names exist in Python (files) and React (screens); change both together.
- The rules above still need the manager's confirmation before launch (`docs/follow-ups.md`).
