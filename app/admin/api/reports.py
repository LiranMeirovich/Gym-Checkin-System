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
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from fastapi.responses import FileResponse, JSONResponse

from app.admin.api.schemas import (
    MonthText,
    NotLoggedIn,
    ReportAnswer,
    ReportMonths,
    ReportRefused,
    ReportRowAnswer,
)
from app.admin.security import StaffLogin, require_permission
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
    )


def _download(month: Month, kind: str) -> FileResponse:
    path = core.file_path(month, kind)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type=_MEDIA_TYPES[kind], filename=path.name)
