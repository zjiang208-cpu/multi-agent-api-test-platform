from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.projects.service import ProjectService
from app.requirements.builder import RequirementBuilder
from app.requirements.requirement_store import RequirementStore

router = APIRouter(prefix="/projects/{project_id}/requirements", tags=["requirements"])


class RequirementBuildRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=200)
    include_optional_evidence: bool = False


class RequirementBuildResponse(BaseModel):
    requirement: RequirementDocument
    evidence: EvidenceBundle


def builder(request: Request) -> RequirementBuilder:
    settings = request.app.state.settings
    projects = ProjectService(request.app.state.project_store, settings.max_projects)
    return RequirementBuilder(projects, settings.resolved_data_dir())


@router.post("/build", response_model=RequirementBuildResponse)
async def build_requirement(
    request: Request,
    project_id: str,
    payload: RequirementBuildRequest,
) -> RequirementBuildResponse:
    result = builder(request).build(
        project_id,
        payload.operation_id,
        include_optional_evidence=payload.include_optional_evidence,
    )
    return RequirementBuildResponse(requirement=result.requirement, evidence=result.evidence)


@router.get("/{requirement_id}", response_model=RequirementDocument)
async def get_requirement(request: Request, project_id: str, requirement_id: str) -> RequirementDocument:
    settings = request.app.state.settings
    ProjectService(request.app.state.project_store, settings.max_projects).get(project_id)
    return RequirementStore(settings.resolved_data_dir(), project_id).get(requirement_id)

