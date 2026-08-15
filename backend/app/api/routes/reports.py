from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.errors import ResourceNotFoundError
from app.models.reports import ReportSnapshot
from app.projects.service import ProjectService
from app.reports.service import ReportService
from app.reports.store import ReportStore
from app.runs.store import RunStore

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])


class ReportBuildRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=200)


def stores(request: Request, project_id: str):
    settings = request.app.state.settings
    ProjectService(request.app.state.project_store, settings.max_projects).get(project_id)
    data_dir = settings.resolved_data_dir()
    return RunStore(data_dir, project_id), ReportStore(data_dir, project_id)


@router.post("/build", response_model=ReportSnapshot)
async def build_report(
    request: Request,
    project_id: str,
    payload: ReportBuildRequest,
) -> ReportSnapshot:
    run_store, report_store = stores(request, project_id)
    run = run_store.get(payload.run_id)
    if run is None:
        raise ResourceNotFoundError(f"run not found: {payload.run_id}")
    report = ReportService.build(run)
    report_store.save(report)
    return report


@router.get("", response_model=list[ReportSnapshot])
async def list_reports(request: Request, project_id: str) -> list[ReportSnapshot]:
    return stores(request, project_id)[1].list()


@router.get("/{report_id}", response_model=ReportSnapshot)
async def get_report(request: Request, project_id: str, report_id: str) -> ReportSnapshot:
    report = stores(request, project_id)[1].get(report_id)
    if report is None:
        raise ResourceNotFoundError(f"report not found: {report_id}")
    return report

