from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.core.errors import ResourceNotFoundError
from app.models.contracts import OperationContract
from app.projects.service import ProjectService
from app.requirements.openapi import OpenApiLoader, SourceLoadError
from app.requirements.operation_store import OperationStore
from app.requirements.operation_yaml import OperationYamlLoadError, OperationYamlLoader


class OperationService:
    def __init__(
        self,
        project_service: ProjectService,
        data_dir: Path,
        *,
        allow_remote_sources: bool = False,
        runtime_session_id: str | None = None,
    ) -> None:
        self.project_service = project_service
        self.data_dir = data_dir
        self.allow_remote_sources = allow_remote_sources
        self.runtime_session_id = runtime_session_id

    def store_for(self, project_id: str) -> OperationStore:
        self.project_service.get(project_id)
        return OperationStore(self.data_dir, project_id)

    def list(self, project_id: str) -> list[OperationContract]:
        return self.store_for(project_id).list(self.runtime_session_id)

    def import_text(self, project_id: str, *, filename: str, content: str) -> list[OperationContract]:
        self.project_service.get(project_id)
        try:
            operations = OperationYamlLoader().discover_text(content.encode("utf-8"), filename)
        except OperationYamlLoadError:
            raise
        tagged = [
            operation.model_copy(update={"runtime_session_id": self.runtime_session_id})
            for operation in operations
        ]
        self.store_for(project_id).save_many(tagged)
        return tagged

    def get(self, project_id: str, operation_id: str) -> OperationContract:
        operation = self.store_for(project_id).get(operation_id, self.runtime_session_id)
        if operation is None:
            raise ResourceNotFoundError(f"operation not found: {operation_id}")
        return operation

    def discover(
        self,
        project_id: str,
        sources: Iterable[str] | None = None,
    ) -> tuple[list[OperationContract], dict[str, str]]:
        project = self.project_service.get(project_id)
        source_list = list(sources or project.settings.openapi_sources)
        if not source_list:
            source_list = [
                source
                for source in project.settings.requirement_sources
                if source.lower().endswith((".yaml", ".yml", ".json"))
            ]
        loader = OpenApiLoader(allow_remote_sources=self.allow_remote_sources)
        yaml_loader = OperationYamlLoader()
        operations: list[OperationContract] = []
        source_status: dict[str, str] = {}
        for source in source_list:
            try:
                discovered = loader.discover(source)
            except SourceLoadError as exc:
                try:
                    discovered = yaml_loader.discover(source)
                except OperationYamlLoadError:
                    source_status[source] = f"error: {exc}"
                    continue
            source_status[source] = f"healthy: {len(discovered)} operations"
            operations.extend(discovered)

        deduped: dict[str, OperationContract] = {}
        for operation in operations:
            existing = deduped.get(operation.operation_id)
            if existing is None:
                deduped[operation.operation_id] = operation
            else:
                references = {
                    item.model_dump_json(): item
                    for item in [*existing.source_refs, *operation.source_refs]
                }
                deduped[operation.operation_id] = existing.model_copy(
                    update={
                        "source_refs": list(references.values()),
                        "source_document_id": existing.source_document_id or operation.source_document_id,
                    }
                )
        tagged = [
            operation.model_copy(update={"runtime_session_id": self.runtime_session_id})
            for operation in deduped.values()
        ]
        self.store_for(project_id).save_many(tagged)
        return self.list(project_id), source_status
