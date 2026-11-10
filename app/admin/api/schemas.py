"""Request and response shapes of the admin API. The frontend's TypeScript
types are generated from these (through the OpenAPI spec), so a change
here that breaks the frontend fails its build."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
)

from app.core.checkins import Outcome
from app.core.health_form_pdf import SIGNATURE_MAX_BYTES
from app.core.health_forms import FormField, FormState
from app.core.http import Answer, DateOfBirth
from app.core.models import CheckInMethod, ChosenBy, Customer, Plan
from app.core.permissions import Permission, Role

# SQLite's integer range. A bigger id can't exist, and SQLite would refuse
# to look it up (a 500), so it's refused as a malformed request instead.
MAX_ID = 2**63 - 1


class NotLoggedIn(Answer):
    """401 from any route that needs a login: no session, or it ended or
    timed out. ``setup_needed`` says to go to first-run setup instead of
    the lock screen."""

    detail: Literal["not_logged_in"] = "not_logged_in"
    setup_needed: bool


# ── The lock screen ─────────────────────────────────────────────────────


class StaffName(Answer):
    id: int
    display_name: str


class LockScreen(Answer):
    """The names to tap; empty with ``setup_needed`` on a fresh install."""

    setup_needed: bool
    staff: list[StaffName]


class LoginRequest(BaseModel):
    staff_id: int = Field(ge=1, le=MAX_ID)
    # Real PINs are 6-12 digits; the cap only keeps a huge value away from
    # the (deliberately slow) PIN check.
    pin: str = Field(max_length=100)


LoginRefusal = Literal["wrong_pin", "locked", "no_such_staff"]


class LoginRefused(Answer):
    """401 from ``POST /api/login``. ``locked_until`` (the gym's local
    time, with its offset) comes with ``locked`` only."""

    error: LoginRefusal
    locked_until: datetime | None = None


# ── A logged-in session ─────────────────────────────────────────────────


class StaffInfo(Answer):
    id: int
    display_name: str
    role: Role


class SessionInfo(Answer):
    """Who is logged in, plus what the page needs to act for them: the
    CSRF token for the ``X-CSRF-Token`` header (kept in memory only), the
    idle time after which the page goes to the lock screen, and the role's
    permissions, so the page offers only what the server would allow
    (every route still checks its own)."""

    staff: StaffInfo
    permissions: list[Permission]
    csrf_token: str
    lock_after_seconds: int


# ── Branding ────────────────────────────────────────────────────────────


class Branding(Answer):
    """The gym's name (null before first-run setup) and whether
    ``/branding/logo`` has a logo to show."""

    gym_name: str | None
    has_logo: bool


# ── First-run setup ─────────────────────────────────────────────────────


class SetupStatus(Answer):
    needed: Literal[True] = True


class SetupRequest(BaseModel):
    gym_name: str
    display_name: str
    pin: str
    pin_again: str


SetupField = Literal["gym_name", "display_name", "pin", "pin_again"]
SetupProblem = Literal["invalid", "mismatch"]


class SetupRefused(Answer):
    """400 from ``POST /api/setup``: every field with a problem, at once.
    ``invalid`` breaks that field's rule; ``mismatch`` is ``pin_again``
    differing from ``pin``. Nothing was saved."""

    errors: dict[SetupField, SetupProblem]


# ── Customers ───────────────────────────────────────────────────────────
# The caps on text only keep a huge value out; the real rules (names 1-50
# characters, notes up to 256, an Israeli phone) are app.core.customers',
# which answers a broken one with a field code, not a 422.

CustomerField = Literal["first_name", "last_name", "phone", "date_of_birth", "notes"]


class CustomerSummary(Answer):
    """A customer's name, phone and whether they're active. ``phone`` is the
    stored E.164 form (``+972501234567``); React formats it for display."""

    id: int
    first_name: str
    last_name: str
    phone: str
    active: bool


class CustomerListRow(CustomerSummary):
    """A row of the customer list. ``last_check_in_at`` is the gym's local
    time, or null if they never checked in."""

    last_check_in_at: datetime | None


class CustomerList(Answer):
    """One page of the list. ``total`` counts every match on all pages;
    ``page`` is the page answered (the last one, for a page past the end)
    and ``page_count`` is at least 1."""

    customers: list[CustomerListRow]
    total: int
    page: int
    page_size: int
    page_count: int


class CustomerName(Answer):
    """Who a dashboard row is about: enough to show the name and link to
    the customer's page."""

    id: int
    first_name: str
    last_name: str

    @classmethod
    def of(cls, customer: Customer) -> "CustomerName":
        return cls(
            id=customer.id,
            first_name=customer.first_name,
            last_name=customer.last_name,
        )


class LatestCustomer(CustomerSummary):
    """A newly added customer. ``created_at`` is the gym's local time, with
    its offset."""

    created_at: datetime


class LatestCustomers(Answer):
    """The newest active customers, newest first, whether added at the desk
    or signed up on their phone (decision 0035)."""

    customers: list[LatestCustomer]


class CustomerDetails(CustomerSummary):
    """One customer's page. ``created_at`` is the gym's local time, with
    its offset."""

    date_of_birth: date
    notes: str
    created_at: datetime


class NewCustomer(BaseModel):
    first_name: str = Field(max_length=200)
    last_name: str = Field(max_length=200)
    phone: str = Field(max_length=50)
    date_of_birth: DateOfBirth
    notes: str = Field(default="", max_length=2000)


class CustomerAdded(Answer):
    """201 from ``POST /api/customers``. ``reactivated``: the phone was an
    inactive customer's, who is active again with their own details (the
    form's others weren't applied)."""

    customer: CustomerDetails
    reactivated: bool


class CustomerEdit(BaseModel):
    """Only the fields sent are changed; the date of birth has its own
    route (manager only)."""

    first_name: str | None = Field(default=None, max_length=200)
    last_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class DateOfBirthChange(BaseModel):
    date_of_birth: DateOfBirth


class CustomerRefused(Answer):
    """400: every field that breaks its rule, at once. Nothing was
    saved."""

    errors: dict[CustomerField, Literal["invalid"]]


class CustomerConflict(Answer):
    """409. ``phone_taken``: another customer has the phone, and
    ``customer_id`` says who, so staff can open their page.
    ``customer_inactive``: reactivate the customer before editing."""

    error: Literal["phone_taken", "customer_inactive"]
    customer_id: int | None = None


# ── Prices ──────────────────────────────────────────────────────────────
# Amounts are whole agorot; React shows and reads shekels. The real limits
# and which months can be chosen are app.core.prices', which answers a broken
# one with a field code, not a 422.

# Four digits from 1000 on, then 01-12: exactly what ``Month.parse`` accepts.
MonthText = Annotated[str, Field(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$")]


class PriceInEffect(Answer):
    """One plan's price this month. Both are ``None`` if it's not set yet."""

    plan: Plan
    amount_agorot: int | None
    valid_from_month: MonthText | None


class PriceRow(Answer):
    """A row as it was entered. ``created_at`` is the gym's local time, with
    its offset."""

    id: int
    plan: Plan
    amount_agorot: int
    valid_from_month: MonthText
    created_at: datetime


class PriceOverview(Answer):
    """``upcoming`` is the change waiting for each later month, soonest
    first. ``history`` is every row ever entered, latest month first."""

    current_month: MonthText
    current: list[PriceInEffect]
    upcoming: list[PriceRow]
    history: list[PriceRow]


class PriceChange(BaseModel):
    # An unknown field is refused, not dropped: a page from before one price
    # per plan (decision 0036) still sends ``age_group``, and its under-18
    # box must not quietly become the plan's price.
    model_config = ConfigDict(extra="forbid")

    plan: Plan
    # Strict, so "100" and 100.0 are malformed rather than quietly converted.
    amount_agorot: int = Field(strict=True)


class PriceChanges(BaseModel):
    """All of them apply from one month, together or not at all."""

    valid_from_month: MonthText
    prices: list[PriceChange] = Field(max_length=50)


class PricesRefused(Answer):
    """400: every part that breaks its rule, at once: ``valid_from_month``,
    or a price by its plan (``monthly``). Nothing was saved."""

    errors: dict[str, Literal["invalid"]]


# ── Plans ───────────────────────────────────────────────────────────────
# What covers a customer's month and the manager's choice. The price is
# looked up on the server and copied onto the choice; a request never
# carries it.


class PlanChoiceRow(Answer):
    """A choice as it was made. ``chosen_at`` is the gym's local time, with
    its offset. ``staff_name`` is who chose it when staff did. ``replaces_id``
    is the choice it corrected, if any; ``replaced_by_id`` the row that
    corrected or cleared it, if any (then it's no longer in force).

    A "no plan" row (``plan`` and ``unit_price_agorot`` both ``None``)
    cleared the choice it replaces; it's never ``covering``."""

    id: int
    plan: Plan | None
    start_month: MonthText
    end_month: MonthText
    unit_price_agorot: int | None
    chosen_at: datetime
    chosen_by: ChosenBy
    staff_name: str | None
    replaces_id: int | None
    replaced_by_id: int | None


class PlanOption(Answer):
    """A plan with its price this month; ``None`` if it's not set, and then
    it can't be chosen."""

    plan: Plan
    amount_agorot: int | None


class PlanStatus(Answer):
    """``covering`` is the choice covering ``current_month``, or ``None``;
    ``correctable`` says whether it may be changed or cleared (it started
    this month). ``history`` is every choice, latest month first."""

    current_month: MonthText
    covering: PlanChoiceRow | None
    correctable: bool
    options: list[PlanOption]
    history: list[PlanChoiceRow]


class PlanChoiceRequest(BaseModel):
    plan: Plan
    # The current month; sent so a page left open over the 1st can't choose
    # for a month it didn't show.
    month: MonthText


class PlanRefused(Answer):
    """400. ``month_not_choosable``: not the current month.
    ``price_not_set``: the manager hasn't entered this plan's price.
    Nothing was saved."""

    error: Literal["month_not_choosable", "price_not_set"]


class PlanConflict(Answer):
    """409. ``month_covered``: a month the plan would cover already has a
    choice, ``choice_id``. ``customer_inactive``: reactivate them first."""

    error: Literal["month_covered", "customer_inactive"]
    choice_id: int | None = None


class PlanCorrectionRequest(BaseModel):
    # The choice to correct; the new row starts in its month.
    replaces_id: int = Field(ge=1, le=MAX_ID)
    # The new plan, or ``None`` (sent explicitly) to clear the choice.
    plan: Plan | None


class CorrectionRefused(Answer):
    """400. ``not_correctable``: the choice started before this month, or
    it's a "no plan" row. ``price_not_set``: as for a choice.
    ``no_change``: same plan, same price. Nothing was saved."""

    error: Literal["not_correctable", "price_not_set", "no_change"]


class CorrectionConflict(Answer):
    """409. ``choice_replaced``: already corrected or cleared, by
    ``choice_id``. ``month_covered``: a month the new plan would cover has
    another choice, ``choice_id``. ``customer_inactive``: reactivate them
    first."""

    error: Literal["choice_replaced", "month_covered", "customer_inactive"]
    choice_id: int | None = None


# ── Linked phones ───────────────────────────────────────────────────────
# Times are the gym's local time, with their offset.


class LinkCodeIssued(Answer):
    """The code to read out to the customer. Shown once: only its hash is
    kept, and a new code cancels this one."""

    code: str
    expires_at: datetime


class LinkedPhone(Answer):
    id: int
    # The phone's browser, as it described itself: only for telling the
    # customer's phones apart.
    user_agent: str
    linked_at: datetime
    last_used_at: datetime


class LinkedPhones(Answer):
    """The customer's live phones, most recently used first."""

    phones: list[LinkedPhone]


# ── Health forms ────────────────────────────────────────────────────────


class HealthFormStatus(Answer):
    """What every staff member sees: ``valid``, ``needs_doctor_note`` (a
    "yes" answer; blocks check-in until a doctor's note is added) or
    ``missing`` (none, or expired). ``valid_until``: the last day of the
    form that counts, or null for ``missing``. Never the answers."""

    state: FormState
    valid_until: date | None


class CustomerFormEntry(Answer):
    """A customer and the form that counts for them today: when it was
    signed and its last valid day. Never the answers."""

    customer: CustomerName
    signed_on: date
    valid_until: date


class CustomerForms(Answer):
    """Customers whose form needs attention, in the order the list gives."""

    forms: list[CustomerFormEntry]


class HealthFormSummary(Answer):
    """One signed form, for the manager. The answers stay in the PDF,
    which is opened (and logged) on its own."""

    id: int
    form_version: str
    signed_on: date
    expires_on: date
    signer_name: str
    signed_by_guardian: bool
    needs_doctor_note: bool
    # The doctor's notes added for this form, oldest first; each image is
    # opened (and logged) on its own.
    doctor_note_ids: list[int]
    # The manager accepted it without a note (decision 0041).
    accepted: bool


class HealthFormList(Answer):
    """Every form the customer has signed, newest first."""

    forms: list[HealthFormSummary]


# The form on the admin PC (the customer signs at the desk): the same
# shapes as the public app's form, which this app must not import, so the
# shared React form works with both.


class HealthFormQuestion(Answer):
    key: str
    text: str
    # The form has a free-text "details" line after this question.
    has_details: bool


class HealthFormPage(Answer):
    """Everything the form shows, in order. The customer's details come
    from their record and can't be changed here. ``guardian_consent`` is
    set when a parent or guardian signs (the customer is under 18 today),
    else null."""

    version: str
    title: str
    customer_name: str
    date_of_birth: date
    phone: str
    wording_note: str
    part_a_title: str
    part_a_notes: list[str]
    questions_intro: str
    questions: list[HealthFormQuestion]
    part_b_title: str
    declaration: list[str]
    guardian_title: str
    guardian_consent: str | None
    # What the signed form's "valid until" will say if signed today.
    valid_until_if_signed: date


# Base64 grows bytes by 4/3, plus the "data:image/png;base64," prefix.
SIGNATURE_DATA_URL_MAX_LENGTH = SIGNATURE_MAX_BYTES * 4 // 3 + 100


class HealthFormRequest(BaseModel):
    """A filled-in form. ``signature`` is the signature pad's PNG as a
    data URL (``data:image/png;base64,...``). The caps only keep junk out;
    ``app.core.health_forms`` has the real rules."""

    version: str = Field(max_length=20)
    # Strict: "true" or 1 is not an answer.
    answers: dict[str, StrictBool] = Field(max_length=50)
    details: dict[
        Annotated[str, StringConstraints(max_length=50)],
        Annotated[str, StringConstraints(max_length=1000)],
    ] = Field(default_factory=dict, max_length=10)
    gender: str = Field(max_length=20)
    signer_name: str = Field(max_length=200)
    confirmed: StrictBool
    signature: str = Field(max_length=SIGNATURE_DATA_URL_MAX_LENGTH)


class HealthFormRefused(Answer):
    """400: every field that breaks its rule, at once. Nothing was
    saved."""

    errors: dict[FormField, Literal["invalid"]]


class HealthFormConflict(Answer):
    """409. ``form_version_changed``: the form changed while the page was
    open; reload it and fill it in again. ``customer_inactive``:
    reactivate them first. Nothing was saved."""

    error: Literal["form_version_changed", "customer_inactive"]


# A shrunk phone photo is far smaller; 12 MB of image is 16 MB of base64.
DOCTOR_NOTE_MAX_CHARS = 16 * 1024 * 1024 + 100


class DoctorNoteRequest(BaseModel):
    """The note as a data URL (``data:image/jpeg;base64,...`` or PNG), as
    the browser reads a file."""

    image: str = Field(max_length=DOCTOR_NOTE_MAX_CHARS)


class DoctorNoteRefused(Answer):
    """400. ``invalid_image``: not a JPEG or PNG, too large or too small.
    Nothing was saved."""

    error: Literal["invalid_image"] = "invalid_image"


class DoctorNoteConflict(Answer):
    """409, from adding a doctor's note or accepting a form without one.
    ``no_note_needed``: the form that counts today isn't waiting for review
    (``state``: ``valid``, or ``missing`` when there is none).
    ``customer_inactive``: reactivate them first. Nothing was saved."""

    error: Literal["no_note_needed", "customer_inactive"]
    state: FormState | None = None


# ── Manual check-in ─────────────────────────────────────────────────────


class ManualCheckInRequest(BaseModel):
    """``plan``: the plan the manager picked, chosen first if no plan
    covers this month (ignored if one does). Only staff with
    ``plans.choose`` may send one; an instructor leaves it out and gets
    single entry when the month has no plan (decision 0017)."""

    plan: Plan | None = None


class CoveringPlan(Answer):
    """The plan covering this month: one month, or three for tri-monthly
    (``end_month`` is the last)."""

    plan: Plan
    start_month: MonthText
    end_month: MonthText


class CheckedIn(Answer):
    """``checked_in``: a visit was recorded. ``already_checked_in``: the
    customer checked in less than 10 minutes ago, by any method, and
    ``checked_in_at`` (the gym's local time) is that visit; nothing new was
    recorded. ``plan`` is null only for a repeat whose month has since
    lost its plan."""

    outcome: Outcome
    checked_in_at: datetime
    plan: CoveringPlan | None


class CheckInHealthFormRequired(Answer):
    """409: no valid health form today (``missing``, or
    ``needs_doctor_note``); nothing was recorded."""

    error: Literal["health_form_required"] = "health_form_required"
    health_form: HealthFormStatus


class CheckInPlanRequired(Answer):
    """409: no plan covers ``month`` and the manager didn't pick one;
    nothing was recorded. Ask for one from ``options`` and send it."""

    error: Literal["plan_required"] = "plan_required"
    month: MonthText
    options: list[PlanOption]


class CheckInRefusedOther(Answer):
    """409. ``price_not_set``: the plan (or an instructor's single entry)
    has no price. ``customer_inactive``:
    reactivate them first. Nothing was recorded."""

    error: Literal["price_not_set", "customer_inactive"]


CheckInRefused = Annotated[
    CheckInHealthFormRequired | CheckInPlanRequired | CheckInRefusedOther,
    Field(discriminator="error"),
]


class CheckInForbidden(Answer):
    """403: a plan was sent by staff who may not choose plans."""

    error: Literal["plan_not_allowed"] = "plan_not_allowed"


class CheckInHistoryEntry(Answer):
    """``checked_in_at`` is the gym's local time; ``method`` is ``phone``
    or ``manual`` (at the desk)."""

    id: int
    checked_in_at: datetime
    method: CheckInMethod


class CheckInHistory(Answer):
    """The customer's latest check-ins, newest first."""

    checkins: list[CheckInHistoryEntry]


class TodaysCheckIn(CheckInHistoryEntry):
    """One of today's check-ins, with who checked in."""

    customer: CustomerName


class TodaysCheckIns(Answer):
    """Every check-in today (the gym's local day), newest first."""

    checkins: list[TodaysCheckIn]


# ── Staff accounts ──────────────────────────────────────────────────────


class StaffMember(Answer):
    """``locked_until`` (the gym's local time, with its offset): locked out
    after too many wrong PINs until then; ``None`` if not locked now. A
    PIN reset lifts it. The ``can_*`` fields say what the logged-in staff
    member may do to this account (decision 0039), so the screen offers
    only that; the routes check the same rules."""

    id: int
    display_name: str
    role: Role
    active: bool
    locked_until: datetime | None
    can_reset_pin: bool
    can_change_role: bool
    # Deactivate, or reactivate an inactive account.
    can_toggle_active: bool


class StaffList(Answer):
    """Every staff account, active ones first."""

    staff: list[StaffMember]


# The roles a staff account can be given; the owner is made only at
# first-run setup (decision 0039).
AssignableRole = Literal["manager", "instructor"]


class NewStaffMember(BaseModel):
    # Generous limits so a long value reaches app.core.staff's own rules
    # (a field code), not a 422.
    display_name: str = Field(max_length=200)
    role: AssignableRole
    pin: str = Field(max_length=100)


class PinReset(BaseModel):
    pin: str = Field(max_length=100)


class RoleChange(BaseModel):
    role: AssignableRole


StaffField = Literal["display_name", "pin"]


class StaffRefused(Answer):
    """400: the field that breaks its rule. Nothing was saved."""

    errors: dict[StaffField, Literal["invalid"]]


StaffConflictReason = Literal["name_taken", "owner"]


class StaffConflict(Answer):
    """409. ``name_taken``: another active staff member has the name.
    ``owner``: the owner's account can't be demoted or deactivated, and
    only the owner resets their own PIN. Nothing was saved."""

    error: StaffConflictReason


# ── Activity log ────────────────────────────────────────────────────────


class ActivityLogQuery(BaseModel):
    """The filters of ``GET /api/activity-log``, all optional. ``from`` and
    ``to`` are the gym's local days, both included. Which combinations make
    sense is checked in ``app.core.activity_log`` (a 400 here)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    staff_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")
    target_type: str | None = Field(default=None, min_length=1, max_length=50)
    target_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    before_id: int | None = Field(default=None, ge=1, le=MAX_ID)


class ActivityLogItem(Answer):
    """One entry. ``action`` and ``target_type`` are the stored names (an
    old entry may use one the code no longer has), and ``before``/``after``
    are whatever the entry stored, in the shape it was written with."""

    id: int
    # The gym's local time, with its offset.
    at: datetime
    staff: StaffName
    action: str
    target_type: str
    target_id: int | None
    # For a staff member or a customer; empty for other targets.
    target_name: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class ActivityLogRefused(Answer):
    """400: the filters can't be used together (a target id without its
    type) or a date is out of range. Nothing to show."""

    error: Literal["invalid_filter"] = "invalid_filter"


class ActivityLogPage(Answer):
    """Newest first. ``next_before_id`` asks for the next, older page; empty
    on the last one."""

    entries: list[ActivityLogItem]
    next_before_id: int | None


# ── Settings ────────────────────────────────────────────────────────────

# The settings the screen edits, named as in ``app.core.gym_settings``.
SettingsField = Literal[
    "gym_name",
    "manager_email",
    "report_recipients",
    "lock_screen_minutes",
    "instructor_lock_screen_minutes",
]


class GymSettingsAnswer(Answer):
    """The current settings. ``problems`` lists the settings whose stored
    value is broken: each shows its default here, and saving the form
    writes a good value over it (decision 0016). ``unknown_settings`` says
    the table holds a row for a setting the code no longer has: every other
    screen refuses to load the settings until a migration removes it, and
    this screen can't."""

    gym_name: str | None
    manager_email: str | None
    report_recipients: list[str]
    lock_screen_minutes: int
    instructor_lock_screen_minutes: int
    problems: list[SettingsField]
    unknown_settings: bool


class SettingsChange(BaseModel):
    """The whole form. ``manager_email: null`` clears it; the gym name
    can't be cleared. The limits only keep huge values out; the rules
    (address format, minute ranges) are ``app.core.gym_settings``'s, and
    break a field, not the request."""

    model_config = ConfigDict(extra="forbid")

    gym_name: str = Field(max_length=500)
    manager_email: str | None = Field(max_length=500)
    report_recipients: list[Annotated[str, Field(max_length=500)]] = Field(
        max_length=50
    )
    lock_screen_minutes: StrictInt
    instructor_lock_screen_minutes: StrictInt


class SettingsRefused(Answer):
    """400: nothing was saved. ``errors`` names each setting that breaks
    its rule: ``invalid``, or ``duplicate`` for an address listed twice in
    ``report_recipients``. ``bad_recipients`` holds the positions (from 0)
    of the recipient addresses that aren't valid."""

    errors: dict[SettingsField, Literal["invalid", "duplicate"]]
    bad_recipients: list[int]
