from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.models.projects import StrictModel


DocumentFormat = Literal["txt", "md", "rst", "html", "json", "yaml", "yml", "docx", "pdf"]
DocumentKind = Literal["requirement_document", "operation_contract", "unknown"]


class DocumentSection(StrictModel):
    section_id: str
    title: str
    level: int = Field(ge=1, le=6)
    content: str = Field(default="", max_length=100_000)
    line_start: int = Field(default=1, ge=1)


class ParsedRequirementDocument(StrictModel):
    document_id: str
    filename: str
    format: DocumentFormat
    detected_kind: DocumentKind = "unknown"
    media_type: str
    content: str = Field(min_length=1, max_length=500_000)
    char_count: int = Field(ge=1)
    line_count: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)
    sections: list[DocumentSection] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class StoredRequirementDocument(ParsedRequirementDocument):
    """Original requirement document persisted for traceability and re-runs."""

    project_id: str | None = Field(default=None, max_length=200)
    runtime_session_id: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
