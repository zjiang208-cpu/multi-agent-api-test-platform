from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from evals.ablation import summarize_ablation
from evals.build_ablation_pack import build_ablation_pack
from evals.annotate_baseline_samples import (
    _assertion_semantically_matches,
    _mapping_for_sample,
)
from evals.dataset import load_manifest
from evals.environment import hydrate_environment_from_project_config
from evals.graders.designer import aggregate_designer, grade_designer
from evals.graders.nlu import grade_nlu
from evals.graders.reviewer import aggregate_reviewer_suite, grade_reviewer
from evals.graders.telemetry import aggregate_telemetry, telemetry_from_metadata
from evals.ground_truth_review import ADDED_POINTS, _strengthen_scenario
from evals.input_audit import audit_input_payload
from evals.models import (
    AssertionMatch,
    AssertionSpec,
    EvalAnnotations,
    EvalDatasetManifest,
    EvalSample,
    GeneratedAssertion,
    GeneratedCase,
    GeneratedPoint,
    GeneratedReviewerOutput,
    GroundTruthOperation,
    GroundTruthPoint,
    PointMatch,
    TelemetryRecord,
)
from evals.runner import load_samples, run_evaluation
from evals.mutations.reviewer_mutations import (
    delete_case,
    duplicate_case,
    make_assertion_path_unsupported,
    remove_required_path_param,
)
from evals.mutations.build_pack import build_reviewer_mutation_pack
from evals.mutations.runtime import mutate_runtime_cases, reviewer_result
from evals.pilot import build_verified_pilot
from app.models.cases import Assertion, CaseSet, RequestTemplate, TestCase
from app.workflow.models import ReviewerAgentOutput


def test_eval_hydrates_missing_user_environment_reference(monkeypatch):
    monkeypatch.delenv("EVAL_TEST_DB_DSN", raising=False)
    monkeypatch.setattr(
        "evals.environment._read_windows_user_environment",
        lambda name: "mysql://redacted" if name == "EVAL_TEST_DB_DSN" else None,
    )

    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".eval-env-test-") as temp_dir:
        root = Path(temp_dir)
        (root / "projects.json").write_text(
            '[{"settings":{"database":{"dsn_ref":"env:EVAL_TEST_DB_DSN"}}}]',
            encoding="utf-8",
        )
        loaded = hydrate_environment_from_project_config([root])

    assert loaded == ["EVAL_TEST_DB_DSN"]
    assert os.getenv("EVAL_TEST_DB_DSN") == "mysql://redacted"


def _ground_truth() -> GroundTruthOperation:
    return GroundTruthOperation(
        operation_id="get-item",
        annotation_status="verified",
        points=[
            GroundTruthPoint(
                point_id="GT-1",
                description="合法请求成功",
                category="positive",
                required_assertions=[
                    AssertionSpec(assertion_id="GT-A-1", type="status_code", expected=200)
                ],
            ),
            GroundTruthPoint(point_id="GT-2", description="资源不存在", category="negative"),
            GroundTruthPoint(
                point_id="GT-3",
                description="非法边界",
                category="boundary",
                verification_mode="observation",
                observation_requirements=["记录查询调用。"],
                preconditions=["准备可观察的查询调用记录。"],
            ),
        ],
    )


def _sample() -> EvalSample:
    return EvalSample(
        sample_id="sample-1",
        operation_id="get-item",
        test_points=[
            GeneratedPoint(point_id="TP-1", title="positive"),
            GeneratedPoint(point_id="TP-2", title="negative"),
            GeneratedPoint(point_id="TP-3", title="boundary"),
        ],
        cases=[
            GeneratedCase(
                case_id="CASE-1",
                test_point_ids=["TP-1"],
                assertions=[GeneratedAssertion(assertion_id="A-1", type="status_code", expected=200)],
                request={"method": "GET", "path": "/items/{id}", "path_params": {"id": 1}},
                executable=True,
            ),
            GeneratedCase(
                case_id="CASE-2",
                test_point_ids=["TP-2"],
                assertions=[GeneratedAssertion(assertion_id="A-2", type="status_code", expected=404)],
                request={"method": "GET", "path": "/items/999"},
                executable=True,
            ),
        ],
        annotations=EvalAnnotations(
            point_matches=[
                PointMatch(generated_point_id="TP-1", ground_truth_point_id="GT-1", supported=True),
                PointMatch(generated_point_id="TP-2", ground_truth_point_id="GT-2", supported=True),
                PointMatch(generated_point_id="TP-3", ground_truth_point_id="GT-3", supported=False),
            ],
            assertion_matches=[
                AssertionMatch(case_id="CASE-1", generated_assertion_id="A-1", ground_truth_assertion_id="GT-A-1")
            ],
        ),
        reviewer_output=GeneratedReviewerOutput(),
    )


def _reviewer_mutation_sample() -> EvalSample:
    """提供 Reviewer Mutation 单元测试所需的最小合成样本。"""

    return EvalSample(
        sample_id="get-shop-id-ci-fixture",
        operation_id="get-shop-id",
        test_points=[
            GeneratedPoint(point_id="tp-get-shop-id-001", title="查询成功"),
            GeneratedPoint(point_id="tp-get-shop-id-002", title="参数无效"),
            GeneratedPoint(point_id="tp-get-shop-id-006", title="资源不存在"),
        ],
        cases=[
            GeneratedCase(
                case_id="CASE-GET-SHOP-001",
                test_point_ids=["tp-get-shop-id-001"],
                assertions=[
                    GeneratedAssertion(
                        assertion_id="ASSERT-GET-SHOP-001-STATUS",
                        type="status_code",
                        expected=200,
                    )
                ],
                request={
                    "method": "GET",
                    "path": "/shop/{id}",
                    "path_params": {"id": 1},
                },
                executable=True,
            ),
            GeneratedCase(
                case_id="CASE-GET-SHOP-002",
                test_point_ids=["tp-get-shop-id-002"],
                assertions=[
                    GeneratedAssertion(
                        assertion_id="ASSERT-GET-SHOP-002-ERRORMSG",
                        type="json_value",
                        path="$.errorMsg",
                        operator="eq",
                        expected="shop id is invalid",
                    )
                ],
                request={
                    "method": "GET",
                    "path": "/shop/{id}",
                    "path_params": {"id": 0},
                },
                executable=True,
            ),
            GeneratedCase(
                case_id="CASE-GET-SHOP-006",
                test_point_ids=["tp-get-shop-id-006"],
                assertions=[
                    GeneratedAssertion(
                        assertion_id="ASSERT-GET-SHOP-006-STATUS",
                        type="status_code",
                        expected=200,
                    )
                ],
                request={
                    "method": "GET",
                    "path": "/shop/{id}",
                    "path_params": {"id": 999999},
                },
                executable=True,
            ),
        ],
        metadata={
            "prompt_version": "synthetic-ci-fixture",
            "llm_nlu_call_1_attempt": "1",
            "llm_nlu_call_1_mode": "generate",
            "llm_nlu_call_1_status": "success",
            "llm_nlu_call_2_attempt": "2",
            "llm_nlu_call_2_mode": "regenerate",
            "llm_nlu_call_2_status": "success",
            "llm_nlu_duration_ms": "34045",
            "llm_designer_call_1_attempt": "1",
            "llm_designer_call_1_mode": "generate",
            "llm_designer_call_1_status": "success",
            "llm_designer_call_2_attempt": "2",
            "llm_designer_call_2_mode": "regenerate",
            "llm_designer_call_2_status": "success",
            "llm_designer_duration_ms": "36308",
            "llm_reviewer_call_1_attempt": "1",
            "llm_reviewer_call_1_mode": "generate",
            "llm_reviewer_call_1_status": "success",
            "llm_reviewer_duration_ms": "77595",
        },
    )


def test_nlu_grader_reports_recall_precision_and_hallucination_without_judge():
    result = grade_nlu(_ground_truth(), _sample(), dataset_status="verified")

    assert result["test_point_recall"]["value"] == 1.0
    assert result["response_test_point_recall"]["value"] == 1.0
    assert result["observation_test_point_recall"]["value"] == 1.0
    assert result["test_point_precision"]["value"] == 0.6667
    assert result["hallucination_rate"]["value"] == 0.3333


def test_designer_grader_counts_point_assertion_executable_and_duplicate_metrics():
    result = grade_designer(_ground_truth(), _sample(), dataset_status="verified")

    assert result["test_point_coverage"]["value"] == 0.6667
    assert result["response_test_point_coverage"]["value"] == 1.0
    assert result["observation_ground_truth_points"] == 1
    assert result["covered_observation_points"] == 0
    assert result["observation_coverage"]["value"] == 0.0
    assert result["assertion_coverage"]["value"] == 1.0
    assert result["executable_case_rate"]["value"] == 1.0
    assert result["duplicate_rate"]["status"] == "ready"


def test_designer_grader_ignores_eval_only_case_fields_when_validating_business_case():
    sample = _sample()
    sample.known_evidence_ids = ["E-1"]
    sample.operation = {
        "operation_id": "get-item",
        "method": "GET",
        "path": "/items/{id}",
        "responses": [{"status_code": 200}],
    }
    sample.cases[0] = sample.cases[0].model_copy(
        update={
            "executable": None,
            "executable_errors": [],
            "requirement_id": "REQ-1",
            "title": "合法请求成功",
            "category": "positive",
            "priority": "high",
            "preconditions": [],
            "steps": ["发送合法 GET 请求"],
            "expected_behavior": "返回 HTTP 200",
            "evidence_refs": ["E-1"],
            "source": "initial",
            "side_effect": False,
        }
    )
    sample.cases[0].assertions[0] = sample.cases[0].assertions[0].model_copy(
        update={"evidence_refs": ["E-1"]}
    )

    result = grade_designer(_ground_truth(), sample, dataset_status="verified")

    assert result["executable_case_rate"]["value"] == 1.0
    assert result["non_executable_cases"] == {}


def test_designer_duplicate_rate_detects_same_execution_for_different_points():
    sample = _sample()
    duplicate = sample.cases[0].model_copy(
        update={"case_id": "CASE-1-DIFFERENT-POINT", "test_point_ids": ["TP-3"]}
    )
    sample.cases.append(duplicate)

    result = grade_designer(_ground_truth(), sample, dataset_status="verified")

    assert result["duplicate_cases"] == 1
    assert result["duplicate_rate"]["value"] == 0.3333


def test_designer_aggregate_uses_micro_assertion_coverage():
    result = aggregate_designer(
        [
            {"required_assertions": 3, "matched_required_assertions": 2},
            {"required_assertions": 4, "matched_required_assertions": 3},
        ]
    )

    assert result["required_assertions"] == 7
    assert result["matched_required_assertions"] == 5
    assert result["assertion_coverage"]["value"] == 0.7143


def test_baseline_assertion_annotation_normalizes_equivalent_operators():
    assert _assertion_semantically_matches(
        {"type": "status_code", "path": None, "operator": None, "expected": 401},
        GeneratedAssertion(type="status_code", operator="eq", expected=401, assertion_id="A-1"),
    )
    assert _assertion_semantically_matches(
        {"type": "json_value", "path": "$.data.length", "operator": "<=", "expected": 10},
        GeneratedAssertion(
            type="json_value",
            path="$.data.length",
            operator="le",
            expected=10,
            assertion_id="A-2",
        ),
    )
    assert _assertion_semantically_matches(
        {"type": "json_exists", "path": "$.total", "operator": None, "expected": False},
        GeneratedAssertion(
            type="json_exists",
            path="$.total",
            operator="eq",
            expected=False,
            assertion_id="A-3",
        ),
    )


def test_current_prompt_annotation_uses_semantic_mapping_without_changing_legacy_mapping():
    current = EvalSample(
        sample_id="current-blog-hot",
        operation_id="get-blog-hot",
        metadata={"designer_prompt_version": "1.6.0"},
        test_points=[
            GeneratedPoint(point_id="TP-BLOG-HOT-001", title="默认成功"),
            GeneratedPoint(point_id="TP-BLOG-HOT-008", title="不提供 total"),
            GeneratedPoint(point_id="TP-BLOG-HOT-009", title="按 liked 和 id 排序"),
        ],
    )
    legacy = current.model_copy(
        update={
            "metadata": {"designer_prompt_version": "1.5.8"},
            "test_points": [
                GeneratedPoint(point_id="tp-get-blog-hot-001", title="排序"),
                GeneratedPoint(point_id="tp-get-blog-hot-007", title="total"),
            ],
        }
    )

    current_mapping = _mapping_for_sample(current)
    legacy_mapping = _mapping_for_sample(legacy)
    assert current_mapping["TP-BLOG-HOT-001"] == "BLOG-008-POSITIVE"
    assert current_mapping["TP-BLOG-HOT-008"] == "BLOG-008-CONTRACT-NO-TOTAL"
    assert current_mapping["TP-BLOG-HOT-009"] == "BLOG-008-CONTRACT-SORT"
    assert legacy_mapping["tp-get-blog-hot-001"] == "BLOG-008-CONTRACT-SORT"
    assert legacy_mapping["tp-get-blog-hot-007"] == "BLOG-008-CONTRACT-NO-TOTAL"


def test_reviewer_mutations_are_known_and_review_metrics_are_deterministic():
    sample = _sample()
    for mutated in (
        delete_case(sample, "CASE-1"),
        remove_required_path_param(sample, "CASE-1", "id"),
        duplicate_case(sample, "CASE-1"),
        make_assertion_path_unsupported(sample, "CASE-1", "A-1"),
    ):
        assert mutated.mutation is not None
        mutated.reviewer_output = GeneratedReviewerOutput(
            **{mutated.mutation.reviewer_field: mutated.mutation.target_ids}
        )
        result = grade_reviewer(mutated)
        assert result["gap_recall"]["value"] == 1.0
        assert result["false_positive_rate"]["value"] == 0.0


def test_reviewer_grader_subtracts_control_findings_and_accepts_any_duplicate_id():
    mutated = duplicate_case(_sample(), "CASE-1")
    mutated.reviewer_output = GeneratedReviewerOutput(
        missing_test_point_ids=["TP-BASE"],
        duplicate_case_ids=["CASE-1__duplicate"],
    )
    control = GeneratedReviewerOutput(missing_test_point_ids=["TP-BASE"])

    result = grade_reviewer(mutated, control)

    assert result["target_match"] == "any"
    assert result["gap_recall"]["value"] == 1.0
    assert result["gap_precision"]["value"] == 1.0
    assert result["false_positive_rate"]["value"] == 0.0


def test_legacy_duplicate_mutation_defaults_to_any_target_match():
    mutation = duplicate_case(_sample(), "CASE-1").mutation
    legacy = mutation.model_dump(exclude={"target_match"})

    migrated = type(mutation).model_validate(legacy)

    assert migrated.target_match == "any"


def test_reviewer_suite_aggregates_defects_after_control_subtraction():
    summary = aggregate_reviewer_suite(
        [
            {
                "variant": "reviewer_mutation",
                "reviewer": {
                    "mutation_id": "M-1",
                    "gap_recall": {"value": 1.0},
                    "detected_targets": ["TP-1"],
                    "extra_findings": [],
                },
            },
            {
                "variant": "reviewer_mutation",
                "reviewer": {
                    "mutation_id": "M-2",
                    "gap_recall": {"value": 0.0},
                    "detected_targets": [],
                    "extra_findings": [],
                },
            },
        ]
    )

    assert summary["defect_recall"]["value"] == 0.5
    assert summary["gap_precision_micro"]["value"] == 1.0
    assert summary["missed_mutation_ids"] == ["M-2"]


def test_verified_pilot_is_independent_from_full_draft_manifest():
    manifest = EvalDatasetManifest(
        dataset_id="baseline",
        version="1.0.0",
        source="requirements",
        annotation_status="draft",
        operations=[_ground_truth().model_copy(update={"annotation_status": "draft"})],
    )

    pilot = build_verified_pilot(manifest, _sample(), "get-item")

    assert manifest.annotation_status == "draft"
    assert manifest.operations[0].annotation_status == "draft"
    assert pilot.annotation_status == "verified"
    assert pilot.operations[0].annotation_status == "verified"
    assert len(pilot.operations) == 1


def test_ablation_pack_keeps_designer_and_reviewer_variants_separate():
    case = _sample().cases[0].model_dump()
    variants = build_ablation_pack(
        _sample(),
        {
            "operation_id": "get-item",
            "draft_cases": {"cases": [case]},
            "final_cases": {"cases": [case]},
            "reviewer_output": {"missing_test_point_ids": ["TP-3"]},
        },
    )

    assert [sample.variant for sample in variants] == ["designer", "reviewer"]
    assert variants[0].reviewer_output is None
    assert variants[1].reviewer_output.missing_test_point_ids == ["TP-3"]
    assert variants[1].metadata["case_count_delta"] == 0


def test_ablation_reports_non_mutation_reviewer_diagnostics():
    sample = _sample().model_copy(
        update={
            "variant": "reviewer",
            "reviewer_output": GeneratedReviewerOutput(
                missing_test_point_ids=["TP-3", "TP-4"],
                invalid_case_ids=["CASE-2"],
                semantic_gaps=["字段类型证据不足"],
            ),
        }
    )

    reviewer = grade_reviewer(sample)
    ablation = summarize_ablation(
        [{"variant": "reviewer", "designer": {}, "reviewer": reviewer}]
    )

    assert reviewer["finding_count_total"] == 4
    assert reviewer["finding_counts"]["missing_test_point_ids"] == 2
    diagnostics = ablation["variants"]["reviewer"]["reviewer_diagnostics"]
    assert diagnostics["status"] == "ready"
    assert diagnostics["finding_count_total"] == 4


def test_ground_truth_review_strengthens_scenarios_and_keeps_added_ids_unique():
    point = GroundTruthPoint(
        point_id="SHOP-004-BOUNDARY-CURRENT",
        description="非法页码",
        category="boundary",
        required_assertions=[
            AssertionSpec(
                assertion_id="SHOP-004-BOUNDARY-CURRENT-ERROR",
                type="json_value",
                path="$.errorMsg",
                expected="current must be greater than 0",
            )
        ],
    )

    added = _strengthen_scenario(point, False)
    added_point_ids = [
        raw_point["point_id"]
        for points in ADDED_POINTS.values()
        for raw_point in points
    ]

    assert added == 2
    assert point.required_assertions[0].type == "status_code"
    assert point.required_assertions[1].path == "$.success"
    assert point.required_assertions[1].expected is False
    assert len(added_point_ids) == len(set(added_point_ids)) == 10


def test_telemetry_aggregates_retry_repair_latency_and_tokens():
    records = telemetry_from_metadata(
        {
            "llm_nlu_call_1_attempt": "1",
            "llm_nlu_call_1_mode": "generate",
            "llm_nlu_call_1_status": "error",
            "llm_nlu_call_1_duration_ms": "10",
            "llm_nlu_call_1_prompt_tokens": "100",
            "llm_nlu_call_2_attempt": "2",
            "llm_nlu_call_2_mode": "repair",
            "llm_nlu_call_2_status": "success",
            "llm_nlu_call_2_duration_ms": "20",
            "llm_nlu_call_2_prompt_tokens": "50",
        }
    )
    result = aggregate_telemetry(records)

    assert result["calls"] == 2
    assert result["duration_ms"] == 30
    assert result["prompt_tokens"] == 150
    assert result["repair_success_rate"]["value"] == 1.0
    assert result["first_pass_success_rate"]["value"] == 0.0


def test_workflow_snapshot_adapter_preserves_evidence_and_telemetry():
    sample = EvalSample.from_workflow_snapshot(
        {
            "operation_id": "get-item",
            "evidence": {"facts": [{"evidence_id": "E-1"}]},
            "metadata": {
                "llm_nlu_call_1_attempt": "1",
                "llm_nlu_call_1_status": "success",
                "llm_nlu_call_1_mode": "generate",
            },
        },
        sample_id="snapshot-1",
    )

    assert sample.known_evidence_ids == ["E-1"]
    assert len(sample.telemetry) == 1


def test_direct_eval_samples_hydrate_telemetry_from_metadata():
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".eval-sample-test-") as temp_dir:
        sample_path = Path(temp_dir) / "synthetic-eval-sample.json"
        sample_path.write_text(
            json.dumps(
                {"samples": [_reviewer_mutation_sample().model_dump(mode="json")]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        samples, _ = load_samples(sample_path, require_redacted=True)

    assert len(samples) == 1
    assert len(samples[0].telemetry) == 5
    assert aggregate_telemetry(samples[0].telemetry)["duration_ms"] == 147948


def test_reviewer_mutation_plan_builds_four_pending_samples():
    project_root = Path(__file__).resolve().parents[2]
    samples = [_reviewer_mutation_sample()]
    import yaml

    plan = yaml.safe_load(
        (project_root / "evals/datasets/baseline_v1/reviewer_mutation_plan.yaml").read_text(encoding="utf-8")
    )
    mutated = build_reviewer_mutation_pack(samples[0], plan)

    assert len(mutated) == 4
    assert {sample.mutation.kind for sample in mutated} == {
        "delete_case",
        "remove_required_path_param",
        "duplicate_case",
        "unsupported_assertion_path",
    }
    assert all(sample.reviewer_output is None for sample in mutated)
    assert all(sample.telemetry == [] for sample in mutated)


def test_runtime_reviewer_mutations_match_the_structured_oracle_fields():
    cases = CaseSet(
        requirement_id="REQ-1",
        test_point_ids=["TP-1"],
        cases=[
            TestCase(
                case_id="CASE-1",
                requirement_id="REQ-1",
                test_point_ids=["TP-1"],
                title="成功查询",
                category="positive",
                steps=["发送请求"],
                expected_behavior="返回成功",
                request=RequestTemplate(method="GET", path="/items/{id}", path_params={"id": 1}),
                assertions=[
                    Assertion(
                        assertion_id="A-1",
                        type="json_value",
                        path="$.success",
                        operator="eq",
                        expected=True,
                    )
                ],
            )
        ],
    )

    missing_path_param = mutate_runtime_cases(
        cases,
        {
            "kind": "remove_required_path_param",
            "target_case_id": "CASE-1",
            "target_parameter_name": "id",
        },
    )
    unsupported = mutate_runtime_cases(
        cases,
        {
            "kind": "unsupported_assertion_path",
            "target_case_id": "CASE-1",
            "target_assertion_id": "A-1",
            "path": "$.data[*].id",
        },
    )

    assert missing_path_param.cases[0].request.path_params == {}
    assert unsupported.cases[0].assertions[0].path == "$.data[*].id"
    assert cases.cases[0].assertions[0].path == "$.success"


def test_reviewer_result_keeps_only_redacted_structured_findings():
    output = ReviewerAgentOutput(
        missing_test_point_ids=["TP-1"],
        semantic_gaps=["CASE-1 缺少成功断言"],
        suggested_case_specs=[],
        unresolved_questions=["需要人工确认"],
    )

    result = reviewer_result(output)

    assert result.missing_test_point_ids == ["TP-1"]
    assert result.semantic_gaps == ["CASE-1 缺少成功断言"]
    assert "suggested_case_specs" not in result.model_dump()
    assert "unresolved_questions" not in result.model_dump()


def test_unverified_dataset_never_emits_quality_numbers_and_ablation_is_explicit():
    manifest = EvalDatasetManifest(
        dataset_id="pending",
        version="1.0.0",
        source="local",
        annotation_status="pending",
        operations=[GroundTruthOperation(operation_id="get-item")],
    )
    assert manifest.annotation_status == "pending"
    result = grade_nlu(manifest.operations[0], _sample(), dataset_status=manifest.annotation_status)
    assert result["test_point_recall"]["value"] is None
    ablation = summarize_ablation(
        [
            {
                "variant": "designer",
                "designer": {"test_point_coverage": {"value": 0.5, "status": "ready"}},
            },
            {
                "variant": "reviewer",
                "designer": {"test_point_coverage": {"value": 0.75, "status": "ready"}},
            },
        ]
    )
    assert ablation["baseline_variant"] == "designer"
    assert ablation["deltas_vs_baseline"]["reviewer"]["test_point_coverage"] == 0.25


def test_redacted_offline_smoke_files_run_the_full_evaluation_path():
    project_root = Path(__file__).resolve().parents[2]
    manifest = load_manifest(project_root / "evals/examples/offline_smoke_manifest.yaml")
    samples, source_summary = load_samples(
        project_root / "evals/examples/offline_smoke_samples.json",
        require_redacted=True,
    )

    report = run_evaluation(manifest, samples, source_summary=source_summary)

    assert report.status == "ready"
    assert len(report.samples) == 2
    assert report.samples[0]["nlu"]["test_point_recall"]["status"] == "ready"
    assert report.samples[0]["designer"]["observation_coverage"]["value"] == 1.0
    assert report.samples[0]["telemetry"]["repair_attempts"] == 1
    assert report.samples[1]["reviewer"]["gap_recall"]["value"] == 1.0
    assert report.samples[1]["reviewer"]["false_positive_rate"]["value"] == 0.0


def test_verified_full_dataset_requires_samples_for_every_operation():
    manifest = EvalDatasetManifest(
        dataset_id="full",
        version="1.0.0",
        source="local",
        annotation_status="verified",
        operations=[
            _ground_truth(),
            _ground_truth().model_copy(update={"operation_id": "get-other"}),
        ],
    )

    report = run_evaluation(manifest, [_sample()])

    assert report.status == "pending_input"
    coverage = report.source_summary["dataset_coverage"]
    assert coverage["sampled_operation_ids"] == ["get-item"]
    assert coverage["missing_operation_ids"] == ["get-other"]


def test_reviewed_missing_assertions_are_scored_as_gaps_not_pending_annotation():
    operation = _ground_truth()
    sample = _sample()
    sample.annotations.assertion_matches = []
    sample.annotations.reviewed_missing_assertion_ids = []
    report = run_evaluation(
        EvalDatasetManifest(
            dataset_id="reviewed-gap",
            version="1.0.0",
            source="local",
            annotation_status="verified",
            operations=[operation],
        ),
        [sample],
    )
    assert report.status == "pending_annotation"

    sample.annotations.reviewed_missing_assertion_ids = [
        "GT-A-1",
    ]
    report = run_evaluation(
        EvalDatasetManifest(
            dataset_id="reviewed-gap",
            version="1.0.0",
            source="local",
            annotation_status="verified",
            operations=[operation],
        ),
        [sample],
    )
    assert report.status == "ready"
    assert report.samples[0]["designer"]["matched_required_assertions"] == 0


def test_input_audit_accepts_smoke_payload_and_rejects_sensitive_values():
    safe = {
        "headers": {"Authorization": "<redacted>"},
        "request": {"path": "/demo/items/<fixture-id>"},
        "metadata": {"prompt_tokens": 10},
    }
    unsafe = {
        "headers": {"Authorization": "Bearer real-token-placeholder"},
        "raw_output": "model output must not be stored",
    }

    assert audit_input_payload(safe)["status"] == "ready"
    result = audit_input_payload(unsafe)
    assert result["status"] == "needs_redaction"
    assert {"sensitive_field", "raw_artifact", "secret_like_value"} <= {
        issue["type"] for issue in result["issues"]
    }


def test_redacted_workflow_snapshot_is_adapted_without_fabricating_annotations():
    project_root = Path(__file__).resolve().parents[2]
    snapshot_path = project_root / "evals/examples/offline_workflow_snapshot.json"
    samples, source_summary = load_samples(snapshot_path, require_redacted=True)

    assert source_summary["format"] == "workflow_snapshot"
    assert len(samples) == 1
    sample = samples[0]
    assert sample.operation_id == "demo-get-item"
    assert sample.operation["path"] == "/demo/items/{id}"
    assert len(sample.test_points) == 2
    assert len(sample.cases) == 2
    assert sample.annotations.point_matches == []
    assert len(sample.telemetry) == 1

    manifest = EvalDatasetManifest(
        dataset_id="offline-snapshot-adapter",
        version="1.0.0",
        source="synthetic",
        annotation_status="verified",
        operations=[
            GroundTruthOperation(
                operation_id="demo-get-item",
                annotation_status="verified",
                points=[
                    GroundTruthPoint(
                        point_id="DEMO-GET-001",
                        description="合成成功点。",
                        category="positive",
                    )
                ],
            )
        ],
    )
    report = run_evaluation(manifest, samples, source_summary=source_summary)

    assert report.status == "pending_annotation"
    assert report.samples[0]["nlu"]["test_point_precision"]["value"] is None
