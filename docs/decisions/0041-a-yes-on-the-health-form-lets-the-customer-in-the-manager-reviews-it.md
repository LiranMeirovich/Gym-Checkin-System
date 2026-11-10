# 0041. A "yes" on the health form lets the customer in; the manager reviews it

- Status: Accepted
- Date: 2026-11-10

## Context
Decision 0031 made any "yes" answer on the health form need a doctor's note before the form counts, and until then check-in was blocked. The dashboard (decision 0040) listed those forms, and forms expiring within 30 days, for everyone at the desk.

The developer judged both lists wrong for the main screen. Forms waiting for a note can sit there for weeks, as people often stop coming, and the instructor gains nothing from watching them. Expiring forms need no one's attention: an expired form sends the customer to the form on their phone at the next check-in, and they can't get in until they sign it.

The developer also expects a doctor's note to be rarely needed in practice, even after a "yes". Blocking those customers until a note arrives turns a rare medical question into a routine refusal at the door. Instead, the customer trains, and the manager looks at the form and decides.

## Options
- **Keep blocking**, and show the instructor when a customer was refused for a missing note. That needs a table of refused attempts, and still sends most "yes" customers home.
- **Let a "yes" form through**, and give the manager a review list. The manager either accepts the form as it is or adds a doctor's note.
- What the manager sees: every form still waiting (until reviewed), or only today's check-ins by customers waiting for a note (gone tomorrow, reviewed or not).
- What the phone shows such a customer: plain success, or success with a reminder to bring a note.

## Decision
- **A form waiting for review lets the customer in**, on the phone and at the desk (`HealthFormStatus.allows_check_in`). Only a missing or expired form blocks, as decision 0004 requires.
- **The phone shows plain success.** It never hears that the form is waiting: the status it gets says "valid" (`as_entry_status()`). The same goes for staff without `health_forms.accept`, so instructors see only valid or missing, as before.
- **The manager reviews each such form**, on the customer's page: they open the form, then either accept it (new `health_forms.accept` permission, owner and managers) or add a doctor's note (as before). Either makes the form count in full.
- **An acceptance is a row in a new append-only table**, `health_form_acceptances` (one per form, who and when). It's logged as `health_form.accept`. Once accepted, the form no longer takes a note.
- **The dashboard drops both form lists.** The owner and managers get a "forms to review" panel instead: every form still waiting, longest wait first, from the existing `/api/health-forms/needing-note` route, which is now theirs only. The expiring-forms route stays, unused.

## Consequences
- **Insurance risk, accepted by the developer:** decision 0004 says the gym isn't insured without a valid form. A customer whose form has a "yes" now trains before anyone has looked at it, and may keep training if the manager never reviews it. Confirm with the insurer that a signed form with a "yes" covers them.
- Instructors no longer see which customers answered "yes". Nothing on the instructor's screen offers a doctor's note any more, though the server still lets them add one.
- An acceptance can't be undone: it stays on record, like a note added by mistake.
- Nothing reminds a customer to bring a note. If notes turn out to matter, the phone can show a reminder later without changing the data.
- Decision 0031's "a yes blocks check-in" and decision 0040's form lists are superseded.
