from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field

from app.models.projects import StrictModel

EvidenceConfidence = Literal["confirmed", "inferred", "question"]


def evidence_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceFact(StrictModel):
    evidence_id: str = Field(default_factory=lambda: f"evidence-{uuid4().hex}")
    source_type: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=1, max_length=1000)
    fact: str = Field(min_length=1, max_length=10_000)
    confidence: EvidenceConfidence = "confirmed"
    operation_id: str | None = None
    safe_excerpt: str | None = Field(default=None, max_length=10_000)
    collected_at: datetime = Field(default_factory=evidence_now)
    metadata: dict[str, str] = Field(default_factory=dict)


class EvidenceBundle(StrictModel):
    operation_id: str
    facts: list[EvidenceFact] = Field(default_factory=list, max_length=1000)
    provider_status: dict[str, str] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list, max_length=200)
    snapshot_id: str = Field(default_factory=lambda: f"snapshot-{uuid4().hex}")

