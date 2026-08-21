from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import AnyHttpUrl, Field, model_validator

from app.models.cases import CaseCategory, CasePriority, CaseSet, TestCase
from app.models.evidence import EvidenceBundle
from app.models.projects import StrictModel
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection


class RequirementAgentOutput(StrictModel):
    """Atomic NLU result: Requirement and Test Points are approved together."""

    requirement: RequirementDocument
    test_points: TestPointCollection


class DesignerAgentOutput(StrictModel):
    draft_cases: CaseSet


class SuggestedCaseSpec(StrictModel):
    """A bounded Reviewer finding that Designer can turn into an API test case."""

    spec_id: str = Field(min_length=1, max_length=200)
    target_test_point_ids: list[str] = Field(min_length=1, max_length=10)
    title: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)
    category: CaseCategory
    priority: CasePriority = "medium"
    required_assertions: list[str] = Field(min_length=1, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class ReviewerAgentOutput(StrictModel):
    """Semantic review findings; scoring and unbounded repair are forbidden."""

    missing_test_point_ids: list[str] = Field(default_factory=list, max_length=1000)
    semantic_gaps: list[str] = Field(default_factory=list, max_length=500)
    invalid_case_ids: list[str] = Field(default_factory=list, max_length=1000)
    duplicate_case_ids: list[str] = Field(default_factory=list, max_length=1000)
    unsupported_assertion_ids: list[str] = Field(default_factory=list, max_length=1000)
    suggested_case_specs: list[SuggestedCaseSpec] = Field(default_factory=list, max_length=5)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=500)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_supplemental_cases(cls, value):
        """Read stored V1 reviews without advertising case generation to the LLM."""

        if isinstance(value, dict) and "supplemental_cases" in value:
            value = {key: item for key, item in value.items() if key != "supplemental_cases"}
        # DeepSeek 偶尔会附带未纳入协议的说明字段；该字段不参与评审结果。
        if isinstance(value, dict) and "unresolved_questions_note" in value:
            value = {
                key: item for key, item in value.items() if key != "unresolved_questions_note"
            }
        return value


FinalCaseStatus = Literal["READY", "NEEDS_CLARIFICATION"]
ExecutionApprovalStatus = Literal["APPROVED", "RUNNING", "CONSUMED", "FAILED"]


class FinalCaseSet(StrictModel):
    final_case_set_id: str
    requirement_id: str
    requirement_fingerprint: str
    source_document_id: str | None = Field(default=None, max_length=200)
    api_operation_id: str | None = Field(default=None, max_length=200)
    cases: list[TestCase] = Field(default_factory=list, max_length=2000)
    added_case_ids: list[str] = Field(default_factory=list, max_length=1000)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=500)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=500)
    status: FinalCaseStatus
    assembly_errors: list[str] = Field(default_factory=list, max_length=500)


class RequirementApproval(StrictModel):
    """Frozen Human Gate #1 snapshot for one API."""

    approval_id: str = Field(default_factory=lambda: f"requirement-approval-{uuid4().hex}")
    workflow_id: str
    project_id: str
    requirement_id: str
    requirement_version: int = Field(ge=1)
    requirement_fingerprint: str
    test_point_count: int = Field(ge=0)
    approved_at: datetime
    status: Literal["APPROVED"] = "APPROVED"


class ExecutionApproval(StrictModel):
    """Human Gate decision captured before any HTTP request is sent."""

    approval_id: str
    workflow_id: str
    project_id: str
    final_case_set_id: str
    requirement_id: str
    requirement_fingerprint: str
    target_environment: str = Field(min_length=1, max_length=120)
    base_url: AnyHttpUrl
    selected_case_ids: list[str] = Field(min_length=1, max_length=2000)
    selected_case_count: int = Field(ge=1, le=2000)
    side_effect_case_ids: list[str] = Field(default_factory=list, max_length=2000)
    side_effects_confirmed: bool
    auto_regression_allowed: bool = True
    status: ExecutionApprovalStatus = "APPROVED"
    manual_run_id: str | None = None
    manual_report_id: str | None = None
    execution_updated_at: datetime | None = None
    approved_at: datetime

    @model_validator(mode="after")
    def validate_confirmation(self) -> "ExecutionApproval":
        if self.selected_case_count != len(self.selected_case_ids):
            raise ValueError("selected_case_count must equal selected_case_ids length")
        if len(set(self.selected_case_ids)) != len(self.selected_case_ids):
            raise ValueError("selected_case_ids must be unique")
        if not set(self.side_effect_case_ids).issubset(set(self.selected_case_ids)):
            raise ValueError("side_effect_case_ids must be selected cases")
        if self.side_effect_case_ids and not self.side_effects_confirmed:
            raise ValueError("side effects must be explicitly confirmed")
        if self.status == "CONSUMED" and (
            self.manual_run_id is None or self.manual_report_id is None
        ):
            raise ValueError("consumed approval must reference its run and report")
        return self


class BatchExecutionApproval(StrictModel):
    """Human Gate #2 snapshot for all Final Cases in one sequential queue."""

    approval_id: str
    queue_run_id: str
    project_id: str
    source_document_id: str
    queue_run_ids: list[str] = Field(default_factory=list, max_length=200)
    source_document_ids: list[str] = Field(default_factory=list, max_length=200)
    final_case_set_ids: list[str] = Field(min_length=1, max_length=200)
    requirement_fingerprints: dict[str, str] = Field(min_length=1, max_length=200)
    target_environment: str = Field(min_length=1, max_length=120)
    base_url: AnyHttpUrl
    selected_case_ids: list[str] = Field(min_length=1, max_length=5000)
    selected_case_count: int = Field(ge=1, le=5000)
    side_effect_case_ids: list[str] = Field(default_factory=list, max_length=5000)
    side_effects_confirmed: bool
    auto_regression_allowed: bool = True
    status: ExecutionApprovalStatus = "APPROVED"
    manual_run_id: str | None = None
    manual_report_id: str | None = None
    execution_updated_at: datetime | None = None
    approved_at: datetime

    @model_validator(mode="after")
    def validate_batch(self) -> "BatchExecutionApproval":
        if self.selected_case_count != len(self.selected_case_ids):
            raise ValueError("selected_case_count must equal selected_case_ids length")
        if len(set(self.selected_case_ids)) != len(self.selected_case_ids):
            raise ValueError("selected_case_ids must be unique")
        if not set(self.side_effect_case_ids).issubset(set(self.selected_case_ids)):
            raise ValueError("side_effect_case_ids must be selected cases")
        if self.side_effect_case_ids and not self.side_effects_confirmed:
            raise ValueError("side effects must be explicitly confirmed")
        if self.status == "CONSUMED" and (
            self.manual_run_id is None or self.manual_report_id is None
        ):
            raise ValueError("consumed approval must reference its run and report")
        return self


WorkflowStatus = Literal[
    "DOCUMENT_PARSED",
    "EVIDENCE_RETRIEVED",
    "REQUIREMENT_READY",
    "WAITING_REQUIREMENT_APPROVAL",
    "DESIGNING",
    "REVIEWING",
    "DRAFT_CASES_READY",
    "FINAL_CASES_READY",
    "NEEDS_CLARIFICATION",
    "FAILED",
]


class WorkflowRunSnapshot(StrictModel):
    """Durable result of the design workflow, including its human-gate input."""

    workflow_id: str
    project_id: str
    operation_id: str
    source_document_id: str | None = Field(default=None, max_length=200)
    status: WorkflowStatus
    requirement: RequirementDocument | None = None
    evidence: EvidenceBundle | None = None
    test_points: TestPointCollection | None = None
    draft_cases: CaseSet | None = None
    reviewer_output: ReviewerAgentOutput | None = None
    final_cases: FinalCaseSet | None = None
    requirement_approval: RequirementApproval | None = None
    errors: list[str] = Field(default_factory=list, max_length=500)
    events: list[dict[str, str]] = Field(default_factory=list, max_length=100)
    metadata: dict[str, str] = Field(default_factory=dict)
