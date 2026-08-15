from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.workflow.models import WorkflowRunSnapshot
from app.workflow.models import ExecutionApproval
from app.workflow.execution import HumanGateService
from app.workflow.service import WorkflowService
from app.projects.service import ProjectService


router = APIRouter(prefix="/projects/{project_id}/workflows", tags=["workflows"])


class WorkflowDesignRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=200)
    include_optional_evidence: bool = False
    requirement_document_id: str | None = Field(default=None, min_length=1, max_length=200)
    requirement_document: str | None = Field(default=None, max_length=50_000)
    workflow_id: str | None = Field(default=None, min_length=1, max_length=200)


class HumanGateApprovalRequest(BaseModel):
    final_case_set_id: str = Field(min_length=1, max_length=200)
    target_environment: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2000)
    case_ids: list[str] = Field(min_length=1, max_length=2000)
    case_count: int = Field(ge=1, le=2000)
    side_effect_case_ids: list[str] = Field(default_factory=list, max_length=2000)
    side_effects_confirmed: bool = False
    auto_regression_allowed: bool = True


def service(request: Request) -> WorkflowService:
    settings = request.app.state.settings
    return WorkflowService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        settings,
    )


@router.post("/design", response_model=WorkflowRunSnapshot)
async def design_workflow(
    request: Request,
    project_id: str,
    payload: WorkflowDesignRequest,
) -> WorkflowRunSnapshot:
    return service(request).run_design(
        project_id,
        payload.operation_id,
        include_optional_evidence=payload.include_optional_evidence,
        input_document_id=payload.requirement_document_id,
        input_document=payload.requirement_document,
        workflow_id=payload.workflow_id,
    )


@router.get("/{workflow_id}", response_model=WorkflowRunSnapshot)
async def get_workflow(
    request: Request,
    project_id: str,
    workflow_id: str,
) -> WorkflowRunSnapshot:
    return service(request).get_run(project_id, workflow_id)


@router.post("/{workflow_id}/approve", response_model=ExecutionApproval)
async def approve_workflow_for_execution(
    request: Request,
    project_id: str,
    workflow_id: str,
    payload: HumanGateApprovalRequest,
) -> ExecutionApproval:
    settings = request.app.state.settings
    gate = HumanGateService(
        ProjectService(request.app.state.project_store, settings.max_projects),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
    )
    return gate.approve(
        project_id,
        workflow_id,
        final_case_set_id=payload.final_case_set_id,
        target_environment=payload.target_environment,
        base_url=payload.base_url,
        case_ids=payload.case_ids,
        case_count=payload.case_count,
        side_effect_case_ids=payload.side_effect_case_ids,
        side_effects_confirmed=payload.side_effects_confirmed,
        auto_regression_allowed=payload.auto_regression_allowed,
    )
