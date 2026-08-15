from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from app.models.projects import StrictModel

CaseCategory = Literal["positive", "negative", "boundary", "contract"]
CasePriority = Literal["high", "medium", "low"]
CaseSource = Literal["initial", "reviewer_added"]
AssertionType = Literal[
    "status_code",
    "json_value",
    "json_type",
    "json_contains",
    "json_exists",
    "header_value",
    "response_schema",
    "response_time_ms",
]


class RequestTemplate(StrictModel):
    method: str
    path: str
    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None


class Assertion(StrictModel):
    assertion_id: str
    type: AssertionType
    path: str | None = None
    expected: Any | None = None
    operator: str | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class TestCase(StrictModel):
    case_id: str
    requirement_id: str
    test_point_ids: list[str] = Field(default_factory=list, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    category: CaseCategory
    priority: CasePriority = "medium"
    preconditions: list[str] = Field(default_factory=list, max_length=100)
    steps: list[str] = Field(min_length=1, max_length=100)
    expected_behavior: str = Field(min_length=1, max_length=3000)
    request: RequestTemplate
    assertions: list[Assertion] = Field(min_length=1, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    source: CaseSource = "initial"
    side_effect: bool = False
    side_effect_note: str | None = Field(default=None, max_length=1000)


class CaseSet(StrictModel):
    requirement_id: str
    test_point_ids: list[str] = Field(default_factory=list, max_length=1000)
    cases: list[TestCase] = Field(default_factory=list, max_length=1000)
    prompt_version: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

