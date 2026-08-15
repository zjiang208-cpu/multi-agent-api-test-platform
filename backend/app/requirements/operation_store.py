from __future__ import annotations

import json
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path
from threading import RLock

from app.models.contracts import OperationContract

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class OperationStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        if not SAFE_ID.fullmatch(project_id):
            raise ValueError("invalid project id")
        self.root_dir = Path(data_dir).expanduser().resolve() / "projects" / project_id
        self.file_path = self.root_dir / "operations.json"
        self._lock = RLock()

    def list(self, runtime_session_id: str | None = None) -> list[OperationContract]:
        with self._lock:
            if not self.file_path.exists():
                return []
            with self.file_path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
        values = [OperationContract.model_validate(item) for item in raw]
        if runtime_session_id is None:
            return values
        return [item for item in values if item.runtime_session_id == runtime_session_id]

    def get(
        self,
        operation_id: str,
        runtime_session_id: str | None = None,
    ) -> OperationContract | None:
        return next(
            (item for item in self.list(runtime_session_id) if item.operation_id == operation_id),
            None,
        )

    def save_many(self, operations: list[OperationContract]) -> list[OperationContract]:
        with self._lock:
            current = {item.operation_id: item for item in self.list()}
            self._merge_operations(current, operations)
            values = sorted(current.values(), key=lambda item: item.operation_id)
            self._write_values(values)
            return values

    def save_requirement_document_operations(
        self,
        document_id: str,
        operations: list[OperationContract],
    ) -> list[OperationContract]:
        """Replace one document's index while retaining every other document."""
        with self._lock:
            current = {
                item.operation_id: item
                for item in self.list()
                if item.contract_metadata.get("discovery") != "requirement_document_parser"
                or item.source_document_id != document_id
            }
            self._merge_operations(current, operations, preserve_document_variants=True)
            values = sorted(current.values(), key=lambda item: item.operation_id)
            self._write_values(values)
            return values

    @staticmethod
    def _merge_operations(
        current: dict[str, OperationContract],
        operations: list[OperationContract],
        *,
        preserve_document_variants: bool = False,
    ) -> None:
        """Keep one catalog entry for each HTTP method and path."""

        for operation in operations:
            if (
                preserve_document_variants
                and operation.operation_id in current
                and current[operation.operation_id].source_document_id != operation.source_document_id
            ):
                suffix = sha256((operation.source_document_id or "document").encode("utf-8")).hexdigest()[:8]
                operation = operation.model_copy(
                    update={"operation_id": f"{operation.operation_id[:191]}-{suffix}"}
                )
            duplicate_ids = [
                operation_id
                for operation_id, existing in current.items()
                if operation_id != operation.operation_id
                and existing.method == operation.method
                and existing.path == operation.path
                and (
                    not preserve_document_variants
                    or existing.source_document_id == operation.source_document_id
                )
            ]
            for operation_id in duplicate_ids:
                del current[operation_id]
            current[operation.operation_id] = operation

    def _write_values(self, values: list[OperationContract]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="operations-", suffix=".tmp", dir=self.root_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    [item.model_dump(mode="json", by_alias=True) for item in values],
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.file_path)
        finally:
            temporary = Path(temp_name)
            if temporary.exists():
                temporary.unlink()
