from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field

from app.models.projects import StrictModel

TestPointCategory = Literal["positive", "negative", "boundary", "contract"]
TestPointPriority = Literal["high", "medium", "low"]
TestPointSource = Literal["requirement", "evidence", "reviewer"]


class TestPoint(StrictModel):
    point_id: str = Field(default_factory=lambda: f"TP-{uuid4().hex}")
    requirement_id: str
    title: str = Field(min_length=1, max_length=500)
    category: TestPointCategory
    priority: TestPointPriority = "medium"
    action: str = Field(min_length=1, max_length=2000)
    expected_result: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    parameter_refs: list[str] = Field(default_factory=list, max_length=100)
    source: TestPointSource = "requirement"


class TestPointCollection(StrictModel):
    requirement_id: str
    requirement_version: int = Field(ge=1)
    points: list[TestPoint] = Field(default_factory=list, max_length=1000)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

