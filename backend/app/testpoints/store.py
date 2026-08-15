from __future__ import annotations

from pathlib import Path

from app.models.testpoints import TestPointCollection
from app.requirements.yaml_store import ArtifactError, YamlArtifactStore


class TestPointStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.artifacts = YamlArtifactStore(
            Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        )

    def save(self, collection: TestPointCollection) -> Path:
        return self.artifacts.save("test-points", collection.requirement_id, collection)

    def get(self, requirement_id: str) -> TestPointCollection:
        return self.artifacts.load("test-points", requirement_id, TestPointCollection)

    def exists(self, requirement_id: str) -> bool:
        try:
            self.get(requirement_id)
        except ArtifactError:
            return False
        return True

