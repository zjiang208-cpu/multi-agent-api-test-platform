from __future__ import annotations

from pathlib import Path

from app.models.requirements import RequirementDocument
from app.requirements.yaml_store import ArtifactError, YamlArtifactStore


class RequirementStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.artifacts = YamlArtifactStore(
            Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        )

    def save(self, requirement: RequirementDocument) -> Path:
        return self.artifacts.save("requirements", requirement.requirement_id, requirement)

    def get(self, requirement_id: str) -> RequirementDocument:
        return self.artifacts.load("requirements", requirement_id, RequirementDocument)

    def exists(self, requirement_id: str) -> bool:
        try:
            self.get(requirement_id)
        except ArtifactError:
            return False
        return True

