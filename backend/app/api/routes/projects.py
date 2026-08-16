from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.executor.auth import AutomaticAuthenticationError
from app.models.projects import AuthRefreshResponse, TestProject, TestProjectCreate, TestProjectUpdate
from app.projects.service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def service(request: Request) -> ProjectService:
    settings = request.app.state.settings
    return ProjectService(request.app.state.project_store, settings.max_projects)


@router.post("", response_model=TestProject, status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, payload: TestProjectCreate) -> TestProject:
    return service(request).create(payload)


@router.get("", response_model=list[TestProject])
async def list_projects(request: Request) -> list[TestProject]:
    return service(request).list()


@router.get("/{project_id}", response_model=TestProject)
async def get_project(request: Request, project_id: str) -> TestProject:
    return service(request).get(project_id)


@router.patch("/{project_id}", response_model=TestProject)
async def update_project(
    request: Request,
    project_id: str,
    payload: TestProjectUpdate,
) -> TestProject:
    project_service = service(request)
    previous = project_service.get(project_id)
    updated = project_service.update(project_id, payload)
    auth_provider = getattr(request.app.state, "auth_provider", None)
    if auth_provider is not None:
        auth_provider.invalidate(project_id, str(previous.settings.sut_target.base_url))
        auth_provider.invalidate(project_id, str(updated.settings.sut_target.base_url))
    return updated


@router.post("/{project_id}/auth/refresh", response_model=AuthRefreshResponse)
async def refresh_project_auth(request: Request, project_id: str) -> AuthRefreshResponse:
    """Perform one explicit credential preflight without returning the token."""

    project = service(request).get(project_id)
    provider = getattr(request.app.state, "auth_provider", None)
    if provider is None:
        return AuthRefreshResponse(
            success=False,
            status="failed",
            message="鉴权服务尚未就绪",
        )
    settings = project.settings
    if not settings.auth_provider.enabled:
        return AuthRefreshResponse(
            success=True,
            status="disabled",
            message="项目未启用可配置鉴权",
        )
    if settings.sut_target.auth_ref:
        return AuthRefreshResponse(
            success=True,
            status="reference",
            message="项目使用外部鉴权引用，平台不主动获取 Token",
        )
    try:
        provider.invalidate(project_id, str(settings.sut_target.base_url))
        credentials = await provider.resolve(
            settings,
            project_id=project_id,
            base_url=str(settings.sut_target.base_url),
            cases=[],
        )
    except AutomaticAuthenticationError as exc:
        return AuthRefreshResponse(success=False, status="failed", message=str(exc))
    if credentials is None:
        return AuthRefreshResponse(
            success=False,
            status="failed",
            message="未能获取可用 Token",
        )
    return AuthRefreshResponse(
        success=True,
        status="refreshed",
        message="Token 获取成功，已保存在后端内存中",
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(request: Request, project_id: str) -> Response:
    project_service = service(request)
    project = project_service.get(project_id)
    project_service.delete(project_id)
    auth_provider = getattr(request.app.state, "auth_provider", None)
    if auth_provider is not None:
        auth_provider.invalidate(project_id, str(project.settings.sut_target.base_url))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
