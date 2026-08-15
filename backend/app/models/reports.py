from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.models.projects import StrictModel


class ReportSnapshot(StrictModel):
    report_id: str
    run_id: str
    project_id: str
    requirement_id: str
    queue_run_id: str | None = None
    status: Literal["passed", "failed", "error", "mixed"]
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    error_cases: int = Field(ge=0)
    assertion_total: int = Field(ge=0)
    assertion_failures: int = Field(ge=0)
    traceability: dict[str, int] = Field(default_factory=dict)
    failure_case_ids: list[str] = Field(default_factory=list)
    by_api: dict[str, dict[str, int]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
