from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.models.contracts import OperationContract
from app.projects.service import ProjectService
from app.requirements.service import OperationService

router = APIRouter(prefix="/projects/{project_id}/operations", tags=["operations"])


class OperationDiscoveryRequest(BaseModel):
    sources: list[str] | None = Field(default=None, max_length=50)


class OperationDiscoveryResponse(BaseModel):
    operations: list[OperationContract]
    source_status: dict[str, str]


class OperationImportTextRequest(BaseModel):
    filename: str = Field(default="uploaded-operation.yaml", min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=500_000)


def service(request: Request) -> OperationService:
    settings = request.app.state.settings
    projects = ProjectService(request.app.state.project_store, settings.max_projects)
    return OperationService(
        projects,
        settings.resolved_data_dir(),
        allow_remote_sources=settings.allow_remote_sources,
        runtime_session_id=request.app.state.runtime_session_id,
    )


@router.post("/discover", response_model=OperationDiscoveryResponse)
async def discover_operations(
    request: Request,
    project_id: str,
    payload: OperationDiscoveryRequest | None = None,
) -> OperationDiscoveryResponse:
    operations, source_status = await run_in_threadpool(
        service(request).discover,
        project_id,
        payload.sources if payload else None,
    )
    return OperationDiscoveryResponse(operations=operations, source_status=source_status)


@router.get("", response_model=list[OperationContract])
async def list_operations(request: Request, project_id: str) -> list[OperationContract]:
    return await run_in_threadpool(service(request).list, project_id)


@router.post("/import-text", response_model=OperationDiscoveryResponse)
async def import_operation_text(
    request: Request,
    project_id: str,
    payload: OperationImportTextRequest,
) -> OperationDiscoveryResponse:
    operations = await run_in_threadpool(
        service(request).import_text,
        project_id,
        filename=payload.filename,
        content=payload.content,
    )
    return OperationDiscoveryResponse(
        operations=operations,
        source_status={payload.filename: f"healthy: {len(operations)} operations"},
    )


@router.get("/{operation_id}", response_model=OperationContract)
async def get_operation(request: Request, project_id: str, operation_id: str) -> OperationContract:
    return await run_in_threadpool(service(request).get, project_id, operation_id)
