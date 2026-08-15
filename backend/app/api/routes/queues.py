from __future__ import annotations

from concurrent.futures import Future

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.models.queue import ApiProcessingQueue
from app.workflow.execution import BatchHumanGateService
from app.workflow.models import BatchExecutionApproval, FinalCaseSet, WorkflowRunSnapshot
from app.workflow.store import WorkflowStore
from app.workflow.queue_service import SequentialQueueService
from app.projects.service import ProjectService


router = APIRouter(prefix="/projects/{project_id}/processing-queues", tags=["processing-queues"])


class QueueCreateRequest(BaseModel):
    source_document_id: str = Field(min_length=1, max_length=200)
    operation_ids: list[str] = Field(min_length=1, max_length=1)


class QueueStartResponse(BaseModel):
    queue: ApiProcessingQueue
    workflow: WorkflowRunSnapshot


class RequirementApprovalRequest(BaseModel):
    requirement_id: str = Field(min_length=1, max_length=200)
    requirement_version: int = Field(ge=1)
    requirement_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)


class BatchExecutionApprovalRequest(BaseModel):
    target_environment: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2000)
    case_ids: list[str] = Field(min_length=1, max_length=5000)
    case_count: int = Field(ge=1, le=5000)
    side_effect_case_ids: list[str] = Field(default_factory=list, max_length=5000)
    side_effects_confirmed: bool = False
    auto_regression_allowed: bool = True


def service(request: Request) -> SequentialQueueService:
    settings = request.app.state.settings
    return SequentialQueueService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        settings,
        runtime_session_id=request.app.state.runtime_session_id,
    )


def _consume_background_result(future: Future) -> None:
    """Observe worker exceptions; queue_service has already persisted the failure."""

    try:
        future.result()
    except Exception:
        pass


@router.post("", response_model=ApiProcessingQueue)
async def create_queue(request: Request, project_id: str, payload: QueueCreateRequest) -> ApiProcessingQueue:
    return service(request).create(project_id, payload.source_document_id, payload.operation_ids)


@router.get("", response_model=list[ApiProcessingQueue])
async def list_queues(request: Request, project_id: str) -> list[ApiProcessingQueue]:
    return service(request).list(project_id)


@router.get("/{run_id}", response_model=ApiProcessingQueue)
async def get_queue(request: Request, project_id: str, run_id: str) -> ApiProcessingQueue:
    return service(request).get(project_id, run_id)


@router.get("/{run_id}/final-cases", response_model=list[FinalCaseSet])
async def get_queue_final_cases(request: Request, project_id: str, run_id: str) -> list[FinalCaseSet]:
    queue = service(request).get(project_id, run_id)
    store = WorkflowStore(request.app.state.settings.resolved_data_dir(), project_id)
    return [store.get_final_cases(item.final_case_set_id) for item in queue.items if item.final_case_set_id]


@router.post("/{run_id}/start", response_model=QueueStartResponse)
async def start_queue(request: Request, project_id: str, run_id: str) -> QueueStartResponse:
    queue, workflow = await run_in_threadpool(service(request).start, project_id, run_id)
    return QueueStartResponse(queue=queue, workflow=workflow)


@router.post("/{run_id}/approve-requirement", response_model=QueueStartResponse)
async def approve_requirement(
    request: Request,
    project_id: str,
    run_id: str,
    payload: RequirementApprovalRequest,
) -> QueueStartResponse:
    queue_service = service(request)
    queue, workflow = await run_in_threadpool(
        queue_service.prepare_current_approval,
        project_id,
        run_id,
        requirement_id=payload.requirement_id,
        requirement_version=payload.requirement_version,
        requirement_fingerprint=payload.requirement_fingerprint or "",
    )
    future = request.app.state.workflow_executor.submit(
        queue_service.continue_current_after_approval,
        project_id,
        run_id,
    )
    future.add_done_callback(_consume_background_result)
    return QueueStartResponse(queue=queue, workflow=workflow)


@router.post("/{run_id}/approve-execution", response_model=BatchExecutionApproval)
async def approve_batch_execution(
    request: Request,
    project_id: str,
    run_id: str,
    payload: BatchExecutionApprovalRequest,
) -> BatchExecutionApproval:
    settings = request.app.state.settings
    gate = BatchHumanGateService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
        runtime_session_id=request.app.state.runtime_session_id,
    )
    return gate.approve(
        project_id,
        run_id,
        target_environment=payload.target_environment,
        base_url=payload.base_url,
        case_ids=payload.case_ids,
        case_count=payload.case_count,
        side_effect_case_ids=payload.side_effect_case_ids,
        side_effects_confirmed=payload.side_effects_confirmed,
        auto_regression_allowed=payload.auto_regression_allowed,
    )
