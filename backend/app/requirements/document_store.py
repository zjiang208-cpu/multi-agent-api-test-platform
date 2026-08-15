from __future__ import annotations

from pathlib import Path

from app.models.documents import StoredRequirementDocument
from app.requirements.yaml_store import ArtifactError, YamlArtifactStore


class RequirementDocumentStore:
    """Durable store for the user's original requirement documents."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        root = Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        self.artifacts = YamlArtifactStore(root)

    def save(self, document: StoredRequirementDocument) -> Path:
        return self.artifacts.save("requirement-documents", document.document_id, document)

    def get(self, document_id: str) -> StoredRequirementDocument:
        return self.artifacts.load("requirement-documents", document_id, StoredRequirementDocument)

    def list(self, runtime_session_id: str | None = None) -> list[StoredRequirementDocument]:
        root = self.artifacts.root_dir / "requirement-documents"
        if not root.is_dir():
            return []
        values: list[StoredRequirementDocument] = []
        for path in sorted(root.glob("*.yaml")):
            try:
                document = self.artifacts.load("requirement-documents", path.stem, StoredRequirementDocument)
                if runtime_session_id is None or document.runtime_session_id == runtime_session_id:
                    values.append(document)
            except ArtifactError:
                continue
        return values
