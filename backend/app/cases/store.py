from __future__ import annotations

from pathlib import Path

from app.models.cases import CaseSet
from app.requirements.yaml_store import YamlArtifactStore


class CaseStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.artifacts = YamlArtifactStore(
            Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        )

    def save(self, cases: CaseSet) -> Path:
        return self.artifacts.save("cases", cases.requirement_id, cases)

    def get(self, requirement_id: str) -> CaseSet:
        return self.artifacts.load("cases", requirement_id, CaseSet)

