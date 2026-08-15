from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.errors import ResourceNotFoundError
from app.models.execution import RunResult
from app.models.reports import ReportSnapshot
from app.runs.store import RunStore
from app.projects.service import ProjectService
from app.workflow.execution import BatchExecutionService, BatchQueueExecutionService

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])


class RunExecutionRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=200)


class BatchExecutionResponse(BaseModel):
    run: RunResult
    report: ReportSnapshot


def ensure_project(request: Request, project_id: str):
    settings = request.app.state.settings
    project = ProjectService(request.app.state.project_store, settings.max_projects).get(project_id)
    return settings, project


@router.post("/execute", response_model=BatchExecutionResponse)
async def execute_run(
    request: Request,
    project_id: str,
    payload: RunExecutionRequest,
) -> BatchExecutionResponse:
    settings, project = ensure_project(request, project_id)
    execution = BatchExecutionService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
        max_response_body_length=settings.max_response_body_length,
        auth_provider=request.app.state.auth_provider,
    )
    run, report = await execution.execute_manual(project_id, payload.approval_id)
    return BatchExecutionResponse(run=run, report=report)


@router.post("/auto-regress", response_model=BatchExecutionResponse)
async def auto_regress(
    request: Request,
    project_id: str,
    payload: RunExecutionRequest,
) -> BatchExecutionResponse:
    settings, _ = ensure_project(request, project_id)
    execution = BatchExecutionService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
        max_response_body_length=settings.max_response_body_length,
        auth_provider=request.app.state.auth_provider,
    )
    run, report = await execution.execute_auto_regression(project_id, payload.approval_id)
    return BatchExecutionResponse(run=run, report=report)


@router.post("/execute-batch", response_model=BatchExecutionResponse)
async def execute_batch_run(
    request: Request,
    project_id: str,
    payload: RunExecutionRequest,
) -> BatchExecutionResponse:
    settings, _ = ensure_project(request, project_id)
    execution = BatchQueueExecutionService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
        max_response_body_length=settings.max_response_body_length,
        auth_provider=request.app.state.auth_provider,
    )
    run, report = await execution.execute_batch(project_id, payload.approval_id)
    return BatchExecutionResponse(run=run, report=report)


@router.post("/auto-regress-batch", response_model=BatchExecutionResponse)
async def auto_regress_batch(
    request: Request,
    project_id: str,
    payload: RunExecutionRequest,
) -> BatchExecutionResponse:
    settings, _ = ensure_project(request, project_id)
    execution = BatchQueueExecutionService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
        max_response_body_length=settings.max_response_body_length,
        auth_provider=request.app.state.auth_provider,
    )
    run, report = await execution.execute_batch(project_id, payload.approval_id, auto_regression=True)
    return BatchExecutionResponse(run=run, report=report)


@router.get("/{run_id}", response_model=RunResult)
async def get_run(request: Request, project_id: str, run_id: str) -> RunResult:
    settings, _ = ensure_project(request, project_id)
    run = RunStore(settings.resolved_data_dir(), project_id).get(run_id)
    if run is None:
        raise ResourceNotFoundError(f"run not found: {run_id}")
    return run
