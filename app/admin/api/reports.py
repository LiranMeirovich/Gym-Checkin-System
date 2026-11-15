"""The monthly report as JSON and files: the manager's Reports screen
(design doc: "Monthly report"). Every route needs ``reports.manage``.

- ``GET /api/reports``: the months a report can be opened for.
- ``GET /api/reports/{month}``: the month's newest generation (the preview)
  and whether one is running.
- ``POST /api/reports/{month}/generate``: start a generation, answered 202
  at once; the work runs after the response, outside this request's
  transaction and its write lock (``app.core.report_generation``). Logged
  there. 409 for an unfinished month or one already being generated.
- ``GET /api/reports/{month}/excel`` and ``.../pdf``: the saved files, as
  downloads. Reading isn't logged. 404 until the month is generated.
- ``POST /api/reports/{month}/approve``: Approve and send the generation
  the screen showed (``report_id``): the approval is recorded and logged
  in this request, the email goes out after the response
  (``app.core.report_delivery``). Answered 202.
- ``POST /api/reports/{month}/resend``: Send again the failed email of
  that generation, the same way. Logged.
- ``GET /api/reports/latest``: the dashboard's report card, where last
  month's report stands.

Approve and resend answer 409 with a code when refused; nothing is
recorded then.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from fastapi.responses import FileResponse, JSONResponse

from app.admin.api.schemas import (
    LatestReportAnswer,
    MonthText,
    NotLoggedIn,
    ReportAnswer,
    ReportApprovalAnswer,
    ReportDeliveryAnswer,
    ReportDeliveryRefused,
    ReportDeliveryRequest,
    ReportEmailAnswer,
    ReportMonths,
    ReportRefused,
    ReportRowAnswer,
)
from app.admin.security import StaffLogin, require_permission
from app.core import report_delivery as delivery
from app.core import report_generation as core
from app.core.clock import to_local
from app.core.db import DbSession
from app.core.months import Month
from app.core.permissions import Permission

router = APIRouter(
    prefix="/reports",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotLoggedIn},
        status.HTTP_403_FORBIDDEN: {},
    },
)

CanManage = Annotated[
    StaffLogin, Depends(require_permission(Permission.REPORTS_MANAGE))
]
MonthPath = Annotated[MonthText, Path()]

_MEDIA_TYPES = {
    core.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    core.PDF: "application/pdf",
}


@router.get("")
def report_months(db: DbSession, _login: CanManage) -> ReportMonths:
    return ReportMonths(months=[str(m) for m in core.report_months(db)])


# Before "/{month}": "latest" isn't a month, so that route would answer 422.
@router.get("/latest")
def latest_report(db: DbSession, _login: CanManage) -> LatestReportAnswer:
    month = delivery.last_month()
    return LatestReportAnswer(
        month=str(month), delivery=_delivery(delivery.status(db, month))
    )


@router.get("/{month}")
def report(month: MonthPath, db: DbSession, _login: CanManage) -> ReportAnswer:
    return _answer(db, Month.parse(month))


@router.post(
    "/{month}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReportAnswer,
    responses={status.HTTP_409_CONFLICT: {"model": ReportRefused}},
)
def generate_report(
    month: MonthPath, db: DbSession, login: CanManage, background: BackgroundTasks
) -> ReportAnswer | JSONResponse:
    wanted = Month.parse(month)
    try:
        job = core.start(wanted, by=login.staff)
    except core.MonthNotFinishedError:
        answer = ReportRefused(error="month_not_finished")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    except core.GenerationRunningError:
        answer = ReportRefused(error="already_generating")
        return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)
    # Runs after the response is sent, when this request's transaction has
    # already committed: the generation opens its own.
    background.add_task(job)
    return _answer(db, wanted)


@router.get(
    "/{month}/excel",
    response_class=FileResponse,
    responses={status.HTTP_200_OK: {"content": {_MEDIA_TYPES[core.EXCEL]: {}}}},
)
def report_excel(month: MonthPath, _login: CanManage) -> FileResponse:
    return _download(Month.parse(month), core.EXCEL)


@router.get(
    "/{month}/pdf",
    response_class=FileResponse,
    responses={status.HTTP_200_OK: {"content": {_MEDIA_TYPES[core.PDF]: {}}}},
)
def report_pdf(month: MonthPath, _login: CanManage) -> FileResponse:
    return _download(Month.parse(month), core.PDF)


_DELIVERY_REFUSALS: dict[type[Exception], str] = {
    delivery.ReportChangedError: "report_changed",
    delivery.GenerationRunningError: "already_generating",
    delivery.SendingError: "already_sending",
    delivery.AlreadyApprovedError: "already_approved",
    delivery.NoRecipientsError: "no_recipients",
    delivery.NothingToResendError: "nothing_to_resend",
}

_DELIVERY_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_409_CONFLICT: {"model": ReportDeliveryRefused}
}


@router.post(
    "/{month}/approve",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReportAnswer,
    responses=_DELIVERY_RESPONSES,
)
def approve_report(
    month: MonthPath,
    body: ReportDeliveryRequest,
    db: DbSession,
    login: CanManage,
    background: BackgroundTasks,
) -> ReportAnswer | JSONResponse:
    wanted = Month.parse(month)
    try:
        job = delivery.start_approve_and_send(
            db, wanted, body.report_id, by=login.staff
        )
    except tuple(_DELIVERY_REFUSALS) as error:
        return _refused(error)
    # Runs after the response, once the approval has committed.
    background.add_task(job)
    return _answer(db, wanted)


@router.post(
    "/{month}/resend",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReportAnswer,
    responses=_DELIVERY_RESPONSES,
)
def resend_report(
    month: MonthPath,
    body: ReportDeliveryRequest,
    db: DbSession,
    login: CanManage,
    background: BackgroundTasks,
) -> ReportAnswer | JSONResponse:
    wanted = Month.parse(month)
    try:
        job = delivery.start_resend(db, wanted, body.report_id, by=login.staff)
    except tuple(_DELIVERY_REFUSALS) as error:
        return _refused(error)
    background.add_task(job)
    return _answer(db, wanted)


def _refused(error: Exception) -> JSONResponse:
    answer = ReportDeliveryRefused.model_validate(
        {"error": _DELIVERY_REFUSALS[type(error)]}
    )
    return JSONResponse(answer.model_dump(), status.HTTP_409_CONFLICT)


def _delivery(current: delivery.DeliveryStatus) -> ReportDeliveryAnswer:
    approval = current.approval
    return ReportDeliveryAnswer(
        report_id=current.report_id,
        stage=current.stage.value,
        manager_email=_email(current.manager_email),
        approval=None
        if approval is None
        else ReportApprovalAnswer(at=to_local(approval.at), by=approval.staff_name),
        recipients_email=_email(current.recipients_email),
        failed_email=None
        if current.failed_email is None
        else current.failed_email.value,
        sending=current.sending,
    )


def _email(step: delivery.EmailStep | None) -> ReportEmailAnswer | None:
    if step is None:
        return None
    return ReportEmailAnswer(
        at=to_local(step.at),
        sent=step.sent,
        recipients=list(step.recipients),
        by=step.staff_name,
    )


def _answer(db: DbSession, month: Month) -> ReportAnswer:
    saved = core.latest(db, month)
    rows = () if saved is None else saved.report.rows
    return ReportAnswer(
        month=str(month),
        generating=core.is_generating(month),
        generated_at=None if saved is None else to_local(saved.generated_at),
        generated_by=None if saved is None else saved.staff_name,
        rows=[
            ReportRowAnswer(
                first_name=row.first_name,
                last_name=row.last_name,
                plans=list(row.plans),
                payment_agorot=row.payment_agorot,
                ends_on=row.ends_on,
            )
            for row in rows
        ],
        total_agorot=0 if saved is None else saved.report.total_agorot,
        files=saved is not None
        and all(core.file_path(month, kind).is_file() for kind in _MEDIA_TYPES),
        delivery=_delivery(delivery.status(db, month)),
    )


def _download(month: Month, kind: str) -> FileResponse:
    path = core.file_path(month, kind)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type=_MEDIA_TYPES[kind], filename=path.name)
