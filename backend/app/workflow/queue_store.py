from __future__ import annotations

from pathlib import Path

from app.models.queue import ApiProcessingQueue
from app.requirements.yaml_store import ArtifactError, YamlArtifactStore


class QueueStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        root = Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        self.artifacts = YamlArtifactStore(root)

    def save(self, queue: ApiProcessingQueue) -> Path:
        return self.artifacts.save("processing-queues", queue.run_id, queue)

    def get(self, run_id: str) -> ApiProcessingQueue:
        return self.artifacts.load("processing-queues", run_id, ApiProcessingQueue)

    def list(self) -> list[ApiProcessingQueue]:
        root = self.artifacts.root_dir / "processing-queues"
        if not root.is_dir():
            return []
        queues: list[ApiProcessingQueue] = []
        for path in root.glob("*.yaml"):
            try:
                queues.append(self.artifacts.load("processing-queues", path.stem, ApiProcessingQueue))
            except ArtifactError:
                continue
        return sorted(queues, key=lambda queue: queue.updated_at, reverse=True)
