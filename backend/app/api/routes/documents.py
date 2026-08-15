from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.models.contracts import OperationContract, SourceReference
from app.models.documents import ParsedRequirementDocument, StoredRequirementDocument
from app.projects.service import ProjectService
from app.requirements.api_discovery import ApiDiscoveryService
from app.requirements.document_parser import (
    MAX_DOCUMENT_BYTES,
    DocumentParseError,
    parse_requirement_document,
)
from app.requirements.document_store import RequirementDocumentStore
from app.requirements.operation_store import OperationStore
from app.requirements.operation_yaml import OperationYamlLoadError, OperationYamlLoader


router = APIRouter(prefix="/requirement-documents", tags=["requirement-documents"])
project_router = APIRouter(prefix="/projects/{project_id}/requirement-documents", tags=["requirement-documents"])


class RequirementDocumentTextRequest(BaseModel):
    filename: str = Field(default="pasted-requirement.md", min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=500_000)


class RequirementDocumentIngestRequest(RequirementDocumentTextRequest):
    pass


class RequirementDocumentDiscoveryResponse(BaseModel):
    document: StoredRequirementDocument
    operations: list[OperationContract]


def _parse_or_raise(*, filename: str, data: bytes, media_type: str | None) -> ParsedRequirementDocument:
    try:
        return parse_requirement_document(filename=filename, data=data, media_type=media_type)
    except DocumentParseError as exc:
        from app.core.errors import DomainError

        raise DomainError(str(exc)) from exc


@router.post("/parse", response_model=ParsedRequirementDocument)
async def parse_uploaded_requirement_document(file: UploadFile = File(...)) -> ParsedRequirementDocument:
    try:
        data = await file.read(MAX_DOCUMENT_BYTES + 1)
    finally:
        await file.close()
    return await run_in_threadpool(
        _parse_or_raise,
        filename=file.filename or "requirement.txt",
        data=data,
        media_type=file.content_type,
    )


@router.post("/parse-text", response_model=ParsedRequirementDocument)
async def parse_pasted_requirement_document(payload: RequirementDocumentTextRequest) -> ParsedRequirementDocument:
    return await run_in_threadpool(
        _parse_or_raise,
        filename=payload.filename,
        data=payload.content.encode("utf-8"),
        media_type="text/markdown",
    )


@project_router.post("/ingest-and-discover", response_model=RequirementDocumentDiscoveryResponse)
async def ingest_and_discover_requirement_document(
    request: Request,
    project_id: str,
    payload: RequirementDocumentIngestRequest,
) -> RequirementDocumentDiscoveryResponse:
    return await run_in_threadpool(
        _ingest_and_discover_requirement_document,
        request,
        project_id,
        payload,
    )


def _ingest_and_discover_requirement_document(
    request: Request,
    project_id: str,
    payload: RequirementDocumentIngestRequest,
) -> RequirementDocumentDiscoveryResponse:
    settings = request.app.state.settings
    ProjectService(request.app.state.project_store, settings.max_projects).get(project_id)
    parsed = _parse_or_raise(
        filename=payload.filename,
        data=payload.content.encode("utf-8"),
        media_type="text/markdown",
    )
    document = StoredRequirementDocument.model_validate(
        parsed.model_dump(mode="json")
        | {
            "project_id": project_id,
            "runtime_session_id": request.app.state.runtime_session_id,
        }
    )
    RequirementDocumentStore(settings.resolved_data_dir(), project_id).save(document)
    if parsed.detected_kind == "operation_contract":
        try:
            contract_operations = OperationYamlLoader().discover_text(
                payload.content.encode("utf-8"),
                payload.filename,
            )
        except OperationYamlLoadError as exc:
            from app.core.errors import DomainError

            raise DomainError(str(exc)) from exc
        operations = [
            operation.model_copy(
                update={
                    "runtime_session_id": request.app.state.runtime_session_id,
                    "source_document_id": document.document_id,
                    "source_refs": [
                        SourceReference(
                            source_document_id=document.document_id,
                            section=operation.summary or document.filename,
                            start_line=1,
                            end_line=document.line_count,
                            heading=operation.summary or document.filename,
                            source_text=document.content[:20_000],
                            reference=f"document:{document.document_id}:full",
                        )
                    ],
                    "contract_metadata": {
                        **operation.contract_metadata,
                        "discovery": "requirement_document_parser",
                    },
                }
            )
            for operation in contract_operations
        ]
    else:
        operations = [
            operation.model_copy(
                update={"runtime_session_id": request.app.state.runtime_session_id}
            )
            for operation in ApiDiscoveryService().discover(document)
        ]
    catalog = OperationStore(settings.resolved_data_dir(), project_id).save_requirement_document_operations(
        document.document_id,
        operations,
    )
    visible_catalog = [
        operation
        for operation in catalog
        if operation.runtime_session_id == request.app.state.runtime_session_id
    ]
    return RequirementDocumentDiscoveryResponse(document=document, operations=visible_catalog)


@project_router.get("", response_model=list[StoredRequirementDocument])
async def list_requirement_documents(request: Request, project_id: str) -> list[StoredRequirementDocument]:
    def load_documents() -> list[StoredRequirementDocument]:
        settings = request.app.state.settings
        ProjectService(request.app.state.project_store, settings.max_projects).get(project_id)
        return RequirementDocumentStore(settings.resolved_data_dir(), project_id).list(
            request.app.state.runtime_session_id
        )

    return await run_in_threadpool(load_documents)


@project_router.get("/{document_id}", response_model=StoredRequirementDocument)
async def get_requirement_document(
    request: Request,
    project_id: str,
    document_id: str,
) -> StoredRequirementDocument:
    def load_document() -> StoredRequirementDocument:
        settings = request.app.state.settings
        ProjectService(request.app.state.project_store, settings.max_projects).get(project_id)
        return RequirementDocumentStore(settings.resolved_data_dir(), project_id).get(document_id)

    return await run_in_threadpool(load_document)
