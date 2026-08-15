from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.models.projects import StrictModel


ProcessingStatus = Literal[
    "PENDING",
    "NLU_RUNNING",
    "WAITING_REQUIREMENT_APPROVAL",
    "DESIGNING",
    "REVIEWING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "SKIPPED",
]

WorkflowStage = Literal[
    "NLU",
    "REQUIREMENT_APPROVAL",
    "DESIGNER",
    "REVIEWER",
    "COMPLETED",
]

QueueStatus = Literal[
    "PENDING",
    "RUNNING",
    "WAITING_REQUIREMENT_APPROVAL",
    "READY_FOR_EXECUTION",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
]


class ApiProcessingItem(StrictModel):
    api_operation_id: str
    order: int = Field(ge=1)
    status: ProcessingStatus = "PENDING"
    current_stage: WorkflowStage = "NLU"
    workflow_id: str | None = None
    requirement_id: str | None = None
    requirement_version: int | None = Field(default=None, ge=1)
    final_case_set_id: str | None = None
    error_message: str | None = Field(default=None, max_length=2000)


class ApiProcessingQueue(StrictModel):
    run_id: str
    runtime_session_id: str | None = Field(default=None, min_length=1, max_length=200)
    project_id: str
    source_document_id: str
    selected_api_ids: list[str] = Field(min_length=1, max_length=200)
    current_index: int = Field(default=0, ge=0)
    status: QueueStatus = "PENDING"
    items: list[ApiProcessingItem] = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
