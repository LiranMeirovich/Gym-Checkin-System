# 0002. Hebrew, right-to-left user interface

- Status: Accepted
- Date: 2026-10-13

## Context
The gym, its staff and its customers are in Israel. Customer names will mostly be in Hebrew, and the monthly report (Excel and PDF) goes to the gym's billing section.

## Options
- **Hebrew only**: everything the users see is in Hebrew, right to left.
- **English only**: simpler to build, but wrong for the people actually using it.
- **Both, with a language switch**: flexible, but every screen and report needs two versions, which is a lot of extra work for no real user.

## Decision
Hebrew is the main and only UI language. Code, comments, commit messages and project docs stay in English.

## Consequences
- Every page uses `<html lang="he" dir="rtl">`, and layouts must be checked in right-to-left, especially on phones.
- **The PDF report needs a library with right-to-left support.** We use fpdf2 with an embedded Hebrew font, not WeasyPrint (which is also hard to install on Windows). Excel (openpyxl) handles Hebrew without extra work.
- Dates, times and money are shown in Israeli formats (Israel time, ₪).
