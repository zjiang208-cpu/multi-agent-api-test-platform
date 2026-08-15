from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.contracts import OperationContract
from app.models.evidence import EvidenceFact
from app.models.projects import ProjectSettings


@dataclass(frozen=True)
class EvidenceContext:
    project_id: str
    operation: OperationContract
    settings: ProjectSettings


@dataclass(frozen=True)
class EvidenceQuery:
    include_optional: bool = False
    max_facts: int = 100


class EvidenceProvider(Protocol):
    provider_type: str

    def health(self, context: EvidenceContext) -> tuple[str, str]:
        """Return state and safe human-readable status."""

    def retrieve(
        self,
        context: EvidenceContext,
        query: EvidenceQuery,
    ) -> list[EvidenceFact]:
        """Return only evidence relevant to the selected operation."""

