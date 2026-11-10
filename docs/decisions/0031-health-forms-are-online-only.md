# 0031. Health forms are online only, on the official form; a "yes" needs a doctor's note

- Status: Accepted; "a yes blocks check-in until a doctor's note" superseded by [0041](0041-a-yes-on-the-health-form-lets-the-customer-in-the-manager-reviews-it.md) (the customer gets in; the manager reviews the form)
- Date: 2026-11-04

## Context
Feature 2 of milestone 3 (decision 0028) builds the health form customers fill in on their phone. The plan was to use placeholder questions until the official form arrived, with paper forms uploaded at the desk as the fallback (design doc: "On paper (at the desk)"; 0028's feature 4). Several of the design doc's details were marked as assumptions: 12 months of validity, and a parent signing for under-18s.

The developer then supplied the gym's current official health declaration. It has 15 yes/no questions (two with a free-text "details" line), gender, a declaration (Part B) and a parent's consent for under-18s. It says a "yes" needs a doctor's certificate, and that the form is valid for the calendar year.

## Options
- **The fallback: paper upload** (staff photograph a signed paper form) vs **online only** (a customer without a phone fills in the same form on a gym tablet or computer at the desk).
- **A "yes" answer: refuse the form**, **accept it as valid**, or **accept it but require a doctor's note** before it counts.
- **Validity: the calendar year** (as the form says) vs **12 months from signing**, either computed when needed or **stored on each row**.
- **The signature: strokes drawn by our own canvas code** vs **a PNG from an established library** (`signature_pad`).
- **The PDF: built inside the request's transaction** (holding the write lock, decision 0027) vs **in a separate step** with its own short transactions.

## Decision
- **Online only.** No paper forms and no scanned-image column. A customer with no phone, or having trouble, fills in the form on a gym device, with the instructor's help. If scans are ever needed, a nullable image column is one migration.
- **The official form's questions**, word for word, under a form version. The gym's name comes from the gym settings, not the code (decision 0006). Gender and the "details" text are stored only in the form's answers, not on the customer. Name, date of birth and phone come from the customer record.
- **Any "yes" makes the form need a doctor's note.** The form is saved (`needs_doctor_note`), but it doesn't count, so check-in stays blocked. Staff must receive the note and add it as an image. Uploading the note, and its table, come in feature 4. The instructor's on-screen notice comes with the dashboard in milestone 4.
- **`expires_on` is stored on each row**, the form's last valid day, 12 months after signing for now. The developer will change the rule once the requirements are clearer. Old rows keep their date.
- **Under-18s: only the parent or guardian signs.**
- **The signature is a PNG** from the `signature_pad` npm package, rather than our own drawing code. The server checks the image with Pillow, which fpdf2 already installs.
- **The PDF snapshot uses fpdf2** with `uharfbuzz` for right-to-left Hebrew shaping and the Noto Sans Hebrew font (OFL licence), committed in the repo. It is built inside the request's transaction, and its speed isn't measured: if staff or customers notice it's slow, it moves out.

## Consequences
- Decision 0028's feature 4 becomes "manual check-in and the form on a gym device". It needs a way to open the form for a customer without a linked phone. To keep that easy, the form's React page is reusable and its core save function doesn't depend on how the customer was found.
- A form's status has three states: valid, needs a doctor's note, or missing/expired. Both of the last two block check-in (decision 0004).
- New dependencies: fpdf2 and uharfbuzz (Python), and `signature_pad` (npm). Milestone 5's reports reuse fpdf2 and the font.
- The official text still says "valid for <year>", and Part B says "all the answers are negative". The phone and the PDF show "valid until <date>" instead of the year. A signer who answered "yes" still signs Part B as written, because it's the official text.
- The design doc's "On paper (at the desk)" section and the 12-month assumption need updating to match.
