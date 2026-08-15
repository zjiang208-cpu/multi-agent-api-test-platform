from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.models.testpoints import TestPointCollection
from app.projects.service import ProjectService
from app.testpoints.generator import TestPointGenerator

router = APIRouter(prefix="/projects/{project_id}/test-points", tags=["test-points"])


class TestPointGenerationRequest(BaseModel):
    requirement_id: str = Field(min_length=1, max_length=200)


def generator(request: Request) -> TestPointGenerator:
    settings = request.app.state.settings
    projects = ProjectService(request.app.state.project_store, settings.max_projects)
    return TestPointGenerator(projects, settings.resolved_data_dir())


@router.post("/generate", response_model=TestPointCollection)
async def generate_test_points(
    request: Request,
    project_id: str,
    payload: TestPointGenerationRequest,
) -> TestPointCollection:
    return generator(request).generate(project_id, payload.requirement_id)


@router.get("/{requirement_id}", response_model=TestPointCollection)
async def get_test_points(request: Request, project_id: str, requirement_id: str) -> TestPointCollection:
    return generator(request).get(project_id, requirement_id)

