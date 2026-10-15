# 0004. A valid health form is required for every check-in

- Status: Accepted
- Date: 2026-10-14

## Context
A new requirement: every customer must sign a health declaration (probably renewed yearly). **Without a valid form, the gym isn't insured if the customer gets injured.** Until now the design doc said entry is never blocked; a missing plan only means the instructor checks the customer in manually.

## Options
- **Google Form + manual matching**: quick to set up, but the health data sits in a second place (someone's Google account), responses must be matched to customers by hand, and there's no proper signature.
- **Built into the system, not blocking**: forms are collected and flagged, but staff can still let someone in without one. That doesn't protect the gym's insurance.
- **Built into the system, blocking**: the form is part of the check-in flow, and no check-in happens without a valid one.

## Decision
Built into the system and blocking, for both phone and manual check-ins. Customers fill it in on their phone with a signature, after linking and before choosing a plan. Staff can upload a signed paper form for customers without a smartphone. Instructors see only whether a form is valid; only the manager opens the contents.

## Consequences
- The check-in flow becomes: phone → health form → plan → checked in. Missing plans still never block entry; missing health forms always do.
- New `health_forms` table, never overwritten. Each signed form is kept as a PDF snapshot, stored inside the database.
- The system now holds health data, which leads to encrypting the database ([0005](0005-encrypt-the-database-with-sqlcipher.md)).
- Existing members must have a form before launch. They'll be registered during the pilot, while the old system is still in use.
- Still to confirm with the manager: the official form, how long it stays valid, and signatures for minors.
