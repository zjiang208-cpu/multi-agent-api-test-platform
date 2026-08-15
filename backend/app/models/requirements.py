from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.models.contracts import OperationContract
from app.models.projects import StrictModel

RequirementConfidence = Literal["confirmed", "inferred", "question"]


class RequirementEvidenceRef(StrictModel):
    evidence_id: str
    source_type: str
    reference: str
    confidence: RequirementConfidence = "confirmed"


class RequirementDocument(StrictModel):
    requirement_id: str
    version: int = Field(default=1, ge=1)
    source_document_id: str | None = Field(default=None, max_length=200)
    api: OperationContract
    preconditions: list[str] = Field(default_factory=list, max_length=200)
    business_rules: list[str] = Field(default_factory=list, max_length=500)
    expected_behaviors: list[str] = Field(default_factory=list, max_length=500)
    conflicts: list[str] = Field(default_factory=list, max_length=200)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=200)
    evidence_refs: list[RequirementEvidenceRef] = Field(default_factory=list, max_length=1000)
    confidence: RequirementConfidence = "confirmed"
    source_snapshot: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    change_summary: str | None = None
