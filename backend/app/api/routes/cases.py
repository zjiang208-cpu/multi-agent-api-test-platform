from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.cases.store import CaseStore
from app.cases.validator import validate_case
from app.models.cases import CaseSet, TestCase
from app.models.evidence import EvidenceBundle, EvidenceFact
from app.models.testpoints import TestPointCollection
from app.projects.service import ProjectService
from app.requirements.requirement_store import RequirementStore
from app.reviewer.service import OnePassReviewService
from app.testpoints.store import TestPointStore
from app.workflow.models import ReviewerAgentOutput
from app.workflow.execution import BatchHumanGateService
from app.workflow.models import BatchExecutionApproval, FinalCaseSet
from app.workflow.project_cases import completed_project_cases

router = APIRouter(prefix="/projects/{project_id}/cases", tags=["cases"])


class CaseValidationRequest(BaseModel):
    case: TestCase


class CaseValidationResponse(BaseModel):
    valid: bool
    errors: list[str]


class CaseReviewRequest(BaseModel):
    requirement_id: str = Field(min_length=1, max_length=200)
    cases: CaseSet


class CaseReviewResponse(BaseModel):
    reviewer_output: ReviewerAgentOutput


class ProjectBatchExecutionApprovalRequest(BaseModel):
    target_environment: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2000)
    case_ids: list[str] = Field(min_length=1, max_length=5000)
    case_count: int = Field(ge=1, le=5000)
    side_effect_case_ids: list[str] = Field(default_factory=list, max_length=5000)
    side_effects_confirmed: bool = False
    auto_regression_allowed: bool = True


def project_service(request: Request) -> ProjectService:
    settings = request.app.state.settings
    return ProjectService(request.app.state.project_store, settings.max_projects)


def context(request: Request, project_id: str, requirement_id: str):
    settings = request.app.state.settings
    project_service(request).get(project_id)
    requirement = RequirementStore(settings.resolved_data_dir(), project_id).get(requirement_id)
    points = TestPointStore(settings.resolved_data_dir(), project_id).get(requirement_id)
    evidence_facts = [
        EvidenceFact(
            evidence_id=ref.evidence_id,
            source_type=ref.source_type,
            reference=ref.reference,
            fact="Persisted evidence reference for the selected requirement.",
            confidence=ref.confidence,
            operation_id=requirement.api.operation_id,
        )
        for ref in requirement.evidence_refs
    ]
    evidence = EvidenceBundle(
        operation_id=requirement.api.operation_id,
        facts=evidence_facts,
    )
    known_evidence = set()
    for ref in requirement.evidence_refs:
        known_evidence.add(ref.evidence_id)
    return requirement, points, evidence, known_evidence


@router.post("/validate", response_model=CaseValidationResponse)
async def validate_case_endpoint(
    request: Request,
    project_id: str,
    payload: CaseValidationRequest,
) -> CaseValidationResponse:
    requirement, points, _, known_evidence = context(request, project_id, payload.case.requirement_id)
    errors = validate_case(
        payload.case,
        known_test_points={item.point_id for item in points.points},
        known_evidence=known_evidence,
        operation=requirement.api,
    )
    if payload.case.requirement_id != requirement.requirement_id:
        errors.append("case requirement_id does not match the selected requirement")
    return CaseValidationResponse(valid=not errors, errors=errors)


@router.post("/review", response_model=CaseReviewResponse)
async def review_cases(
    request: Request,
    project_id: str,
    payload: CaseReviewRequest,
) -> CaseReviewResponse:
    requirement, points, evidence, _ = context(request, project_id, payload.requirement_id)
    if payload.cases.requirement_id != requirement.requirement_id:
        raise ValueError("case set requirement_id does not match the selected requirement")
    reviewer_output = OnePassReviewService().review(requirement, points, payload.cases, evidence)
    return CaseReviewResponse(reviewer_output=reviewer_output)


@router.post("/save", response_model=CaseSet)
async def save_cases(request: Request, project_id: str, payload: CaseSet) -> CaseSet:
    context(request, project_id, payload.requirement_id)
    CaseStore(request.app.state.settings.resolved_data_dir(), project_id).save(payload)
    return payload


@router.get("/final", response_model=list[FinalCaseSet])
async def list_project_final_cases(request: Request, project_id: str) -> list[FinalCaseSet]:
    project_service(request).get(project_id)
    data_dir = request.app.state.settings.resolved_data_dir()
    return [
        entry.final_cases
        for entry in completed_project_cases(
            data_dir,
            project_id,
            runtime_session_id=request.app.state.runtime_session_id,
        )
    ]


@router.post("/approve-execution", response_model=BatchExecutionApproval)
async def approve_project_execution(
    request: Request,
    project_id: str,
    payload: ProjectBatchExecutionApprovalRequest,
) -> BatchExecutionApproval:
    settings = request.app.state.settings
    gate = BatchHumanGateService(
        project_service(request),
        settings.resolved_data_dir(),
        allow_remote_targets=settings.allow_remote_targets,
        runtime_session_id=request.app.state.runtime_session_id,
    )
    return gate.approve_project(
        project_id,
        target_environment=payload.target_environment,
        base_url=payload.base_url,
        case_ids=payload.case_ids,
        case_count=payload.case_count,
        side_effect_case_ids=payload.side_effect_case_ids,
        side_effects_confirmed=payload.side_effects_confirmed,
        auto_regression_allowed=payload.auto_regression_allowed,
    )


@router.get("/{requirement_id}", response_model=CaseSet)
async def get_cases(request: Request, project_id: str, requirement_id: str) -> CaseSet:
    project_service(request).get(project_id)
    return CaseStore(request.app.state.settings.resolved_data_dir(), project_id).get(requirement_id)
