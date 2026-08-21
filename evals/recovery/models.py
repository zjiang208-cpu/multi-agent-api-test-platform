from __future__ import annotations

from typing import Literal

from pydantic import Field

from evals.models import EvalModel, GeneratedCase, GeneratedReviewerOutput, TelemetryRecord


RecoveryMutationKind = Literal["delete_case"]


class RecoveryMutationSpec(EvalModel):
    """A controlled omission whose recovery can be scored against Ground Truth."""

    mutation_id: str
    kind: RecoveryMutationKind
    target_case_id: str
    target_test_point_ids: list[str] = Field(min_length=1)
    target_match: Literal["all", "any"] = "all"
    description: str


class RecoveryEvalSample(EvalModel):
    """Redacted result of Reviewer -> Supplement -> Validator evaluation."""

    sample_id: str
    operation_id: str
    variant: Literal["recovery_control", "recovery_mutation"]
    original_cases: list[GeneratedCase] = Field(default_factory=list)
    mutated_cases: list[GeneratedCase] = Field(default_factory=list)
    reviewer_initial_output: GeneratedReviewerOutput | None = None
    reviewer_initial_suggested_test_point_ids: list[str] = Field(default_factory=list)
    reviewer_output: GeneratedReviewerOutput | None = None
    reviewer_suggested_test_point_ids: list[str] = Field(default_factory=list)
    supplemental_cases: list[GeneratedCase] = Field(default_factory=list)
    final_cases: list[GeneratedCase] = Field(default_factory=list)
    final_status: Literal["READY", "NEEDS_CLARIFICATION"] | None = None
    final_added_case_ids: list[str] = Field(default_factory=list)
    final_remaining_gaps: list[str] = Field(default_factory=list)
    final_assembly_errors: list[str] = Field(default_factory=list)
    mutation: RecoveryMutationSpec | None = None
    telemetry: list[TelemetryRecord] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
