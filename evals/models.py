from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvalCategory = Literal["positive", "negative", "boundary", "auth", "contract"]
VerificationMode = Literal["response_assertion", "observation"]
AnnotationStatus = Literal["pending", "draft", "verified"]
FixtureKind = Literal["database", "auth", "cache", "state", "observation"]
FixtureResolution = Literal["local_token", "manual_setup", "manual_observation"]
_SAFE_FIXTURE_TOKEN = re.compile(r"^\$(?:DB|AUTH)_FIXTURE\[[^\]\r\n]+\]$")


class EvalModel(BaseModel):
    """Base model that accepts stored workflow fields without losing them."""

    model_config = ConfigDict(extra="allow")


class AssertionSpec(EvalModel):
    assertion_id: str
    type: str
    path: str | None = None
    operator: str | None = None
    expected: Any | None = None
    description: str | None = None
    required: bool = True


class FixtureRequirement(EvalModel):
    """A redacted fixture or setup requirement for a ground-truth point."""

    reference: str = Field(min_length=1)
    kind: FixtureKind
    description: str = Field(min_length=1)
    resolution: FixtureResolution = "manual_setup"
    token: str | None = None

    @model_validator(mode="after")
    def validate_token_resolution(self) -> "FixtureRequirement":
        if self.resolution == "local_token":
            if not self.token or not _SAFE_FIXTURE_TOKEN.fullmatch(self.token):
                raise ValueError("local_token fixture requirements must use a safe fixture token")
        elif self.token is not None:
            raise ValueError("manual fixture requirements must not contain a token")
        return self


class GroundTruthPoint(EvalModel):
    point_id: str
    description: str = Field(min_length=1)
    category: EvalCategory
    required_assertions: list[AssertionSpec] = Field(default_factory=list)
    verification_mode: VerificationMode = "response_assertion"
    observation_requirements: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    fixture_requirements: list[FixtureRequirement] = Field(default_factory=list)


class GroundTruthOperation(EvalModel):
    operation_id: str
    method: str | None = None
    path: str | None = None
    source_reference: str | None = None
    annotation_status: AnnotationStatus = "pending"
    points: list[GroundTruthPoint] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def verified_dataset_must_have_points(self) -> "GroundTruthOperation":
        if self.annotation_status == "verified" and not self.points:
            raise ValueError("verified operation must define at least one ground-truth point")
        return self


class EvalDatasetManifest(EvalModel):
    dataset_id: str
    version: str
    source: str
    annotation_status: AnnotationStatus = "pending"
    operations: list[GroundTruthOperation] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def verified_dataset_must_be_annotated(self) -> "EvalDatasetManifest":
        if self.annotation_status == "verified":
            if not self.operations:
                raise ValueError("verified dataset must contain operations")
            if any(operation.annotation_status != "verified" for operation in self.operations):
                raise ValueError("all operations must be verified before dataset scoring")
        return self


class GeneratedPoint(EvalModel):
    point_id: str
    title: str = ""
    category: str | None = None


class GeneratedAssertion(EvalModel):
    assertion_id: str
    type: str
    path: str | None = None
    operator: str | None = None
    expected: Any | None = None


class GeneratedCase(EvalModel):
    case_id: str
    test_point_ids: list[str] = Field(default_factory=list)
    assertions: list[GeneratedAssertion] = Field(default_factory=list)
    request: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    executable: bool | None = None
    executable_errors: list[str] = Field(default_factory=list)


class GeneratedReviewerOutput(EvalModel):
    missing_test_point_ids: list[str] = Field(default_factory=list)
    invalid_case_ids: list[str] = Field(default_factory=list)
    duplicate_case_ids: list[str] = Field(default_factory=list)
    unsupported_assertion_ids: list[str] = Field(default_factory=list)
    semantic_gaps: list[str] = Field(default_factory=list)
    remaining_gaps: list[str] = Field(default_factory=list)


class PointMatch(EvalModel):
    generated_point_id: str
    ground_truth_point_id: str | None = None
    supported: bool = False
    notes: str | None = None


class AssertionMatch(EvalModel):
    case_id: str
    generated_assertion_id: str
    ground_truth_assertion_id: str
    notes: str | None = None


class EvalAnnotations(EvalModel):
    """Human annotations required for semantic NLU/Designer metrics."""

    point_matches: list[PointMatch] = Field(default_factory=list)
    assertion_matches: list[AssertionMatch] = Field(default_factory=list)
    # 已人工确认“模型未生成”的必要断言，计入漏测而不是评测待标注。
    reviewed_missing_assertion_ids: list[str] = Field(default_factory=list)


class TelemetryRecord(EvalModel):
    stage: str
    attempt: int = 1
    duration_ms: int = 0
    stage_duration_ms: int | None = None
    status: str
    mode: str = "generate"
    error_category: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None


class MutationSpec(EvalModel):
    mutation_id: str
    kind: Literal[
        "delete_case",
        "remove_required_path_param",
        "remove_all_assertions",
        "duplicate_case",
        "unsupported_assertion_path",
    ]
    reviewer_field: Literal[
        "missing_test_point_ids",
        "invalid_case_ids",
        "unsupported_assertion_ids",
        "duplicate_case_ids",
    ]
    target_ids: list[str] = Field(min_length=1)
    target_match: Literal["all", "any"] = "all"
    description: str

    @model_validator(mode="before")
    @classmethod
    def migrate_duplicate_target_matching(cls, value):
        """旧版重复用例样本按缺陷计数，不要求重复对的两个 ID 同时返回。"""

        if isinstance(value, dict) and value.get("kind") == "duplicate_case":
            value = dict(value)
            value["target_match"] = "any"
        return value


class EvalSample(EvalModel):
    sample_id: str
    operation_id: str
    variant: str = "full"
    operation: dict[str, Any] | None = None
    known_evidence_ids: list[str] = Field(default_factory=list)
    test_points: list[GeneratedPoint] = Field(default_factory=list)
    cases: list[GeneratedCase] = Field(default_factory=list)
    reviewer_output: GeneratedReviewerOutput | None = None
    annotations: EvalAnnotations = Field(default_factory=EvalAnnotations)
    telemetry: list[TelemetryRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    mutation: MutationSpec | None = None

    @classmethod
    def from_workflow_snapshot(
        cls,
        payload: dict[str, Any],
        *,
        sample_id: str,
        variant: str = "full",
        annotations: EvalAnnotations | None = None,
    ) -> "EvalSample":
        points_payload = (payload.get("test_points") or {}).get("points") or []
        final_payload = payload.get("final_cases") or payload.get("draft_cases") or {}
        cases_payload = final_payload.get("cases") or []
        requirement = payload.get("requirement") or {}
        operation = requirement.get("api") if isinstance(requirement, dict) else None
        metadata = payload.get("metadata") or {}
        evidence = payload.get("evidence") or {}
        evidence_ids = [
            fact.get("evidence_id")
            for fact in evidence.get("facts", [])
            if isinstance(fact, dict) and fact.get("evidence_id")
        ]
        from evals.graders.telemetry import telemetry_from_metadata

        return cls(
            sample_id=sample_id,
            operation_id=str(payload.get("operation_id") or requirement.get("operation_id") or ""),
            variant=variant,
            operation=operation,
            known_evidence_ids=evidence_ids,
            test_points=points_payload,
            cases=cases_payload,
            reviewer_output=payload.get("reviewer_output"),
            annotations=annotations or EvalAnnotations(),
            telemetry=telemetry_from_metadata(metadata),
            metadata=metadata,
        )


class MetricValue(EvalModel):
    value: float | None = None
    numerator: int | float = 0
    denominator: int | float = 0
    status: Literal["ready", "pending_annotation", "pending_input"]
    reason: str | None = None


class EvalReport(EvalModel):
    dataset_id: str
    dataset_version: str
    generated_at: str
    status: Literal["ready", "pending_annotation", "pending_input"]
    samples: list[dict[str, Any]] = Field(default_factory=list)
    reviewer_summary: dict[str, Any] = Field(default_factory=dict)
    ablation: dict[str, Any] = Field(default_factory=dict)
    # 组件级和端到端指标分栏，避免把 Reviewer Mutation 结果误读成系统质量。
    component_eval: dict[str, Any] = Field(default_factory=dict)
    e2e_eval: dict[str, Any] = Field(default_factory=dict)
    telemetry_summary: dict[str, Any] = Field(default_factory=dict)
    source_summary: dict[str, Any] = Field(default_factory=dict)
