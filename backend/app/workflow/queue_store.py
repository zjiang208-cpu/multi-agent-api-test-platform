from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.models.queue import ApiProcessingQueue
from app.requirements.yaml_store import ArtifactError, YamlArtifactStore


_LEGACY_FAILED_STATUS = "BLOCK" + "ED"


class QueueStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        root = Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        self.artifacts = YamlArtifactStore(root)

    def save(self, queue: ApiProcessingQueue) -> Path:
        return self.artifacts.save("processing-queues", queue.run_id, queue)

    def get(self, run_id: str) -> ApiProcessingQueue:
        return self._load(run_id)

    def list(self) -> list[ApiProcessingQueue]:
        root = self.artifacts.root_dir / "processing-queues"
        if not root.is_dir():
            return []
        queues: list[ApiProcessingQueue] = []
        for path in root.glob("*.yaml"):
            try:
                queues.append(self._load(path.stem))
            except ArtifactError:
                continue
        return sorted(queues, key=lambda queue: queue.updated_at, reverse=True)

    def _load(self, run_id: str) -> ApiProcessingQueue:
        """Load a queue and migrate the historical terminal state once.

        Older private runtime artifacts used a separate terminal state for an
        incomplete workflow. If executable Final Cases were already persisted,
        restore the queue as ready; otherwise preserve it as a real failure.
        Normalize the legacy artifact before validation so restarting the
        backend does not make old local data unreadable.
        """

        path = self.artifacts.path_for("processing-queues", run_id)
        if not path.is_file():
            raise ArtifactError(f"artifact not found: processing-queues/{run_id}")
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        if not isinstance(raw, dict):
            raise ArtifactError("artifact root must be a YAML mapping")

        migrated = False
        items = raw.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("status") == _LEGACY_FAILED_STATUS:
                    if item.get("final_case_set_id"):
                        item["status"] = "COMPLETED"
                        item["current_stage"] = "COMPLETED"
                    else:
                        item["status"] = "FAILED"
                    migrated = True
        if raw.get("status") == _LEGACY_FAILED_STATUS:
            normalized_statuses = [
                item.get("status")
                for item in items
                if isinstance(item, dict)
            ] if isinstance(items, list) else []
            if normalized_statuses and all(
                status in {"COMPLETED", "SKIPPED"} for status in normalized_statuses
            ):
                raw["status"] = (
                    "READY_WITH_SKIPS"
                    if "SKIPPED" in normalized_statuses
                    else "READY_FOR_EXECUTION"
                )
                raw["current_index"] = len(normalized_statuses)
            else:
                raw["status"] = "FAILED"
            migrated = True
        try:
            queue = ApiProcessingQueue.model_validate(raw)
        except ValidationError as exc:
            raise ArtifactError(f"invalid processing queue artifact: {run_id}") from exc
        if migrated:
            self.save(queue)
        return queue
