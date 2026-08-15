from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from app.models.projects import StrictModel

ExecutionStatus = Literal["passed", "failed", "error", "skipped"]


class AssertionResult(StrictModel):
    assertion_id: str
    type: str | None = None
    path: str | None = None
    operator: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    passed: bool
    message: str
    expected: Any | None = None
    actual: Any | None = None


class ExecutionResult(StrictModel):
    result_id: str
    case_id: str
    case_title: str | None = None
    requirement_id: str
    api_operation_id: str | None = None
    status: ExecutionStatus
    method: str
    url: str
    status_code: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: Any | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    error_category: str | None = None
    error_message: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunResult(StrictModel):
    run_id: str
    project_id: str
    requirement_id: str
    queue_run_id: str | None = None
    approval_id: str | None = None
    target_environment: str | None = None
    base_url: str | None = None
    results: list[ExecutionResult] = Field(default_factory=list)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
