from __future__ import annotations

import json

from app.models.cases import Assertion, CaseSet, RequestTemplate, TestCase as BackendTestCase
from evals.graders.recovery import aggregate_recovery, grade_recovery
from evals.models import GeneratedCase, GeneratedReviewerOutput
from evals.recovery.models import RecoveryEvalSample, RecoveryMutationSpec
from evals.recovery.runtime import mutate_recovery_cases
from evals.recovery.validation import validate_recovery_suite
from evals.recovery_experiment import build_experiment_report

def _case(case_id: str, point_id: str) -> GeneratedCase:
    return GeneratedCase(
        case_id=case_id,
        test_point_ids=[point_id],
        assertions=[],
        request={"method": "GET", "path": "/demo"},
    )


def _mutation() -> RecoveryMutationSpec:
    return RecoveryMutationSpec(
        mutation_id="delete-case:CASE-2:recovery",
        kind="delete_case",
        target_case_id="CASE-2",
        target_test_point_ids=["TP-2"],
        description="delete one required case",
    )


def test_recovery_grader_scores_detection_and_final_recovery():
    sample = RecoveryEvalSample(
        sample_id="sample-1",
        operation_id="op-1",
        variant="recovery_mutation",
        original_cases=[_case("CASE-1", "TP-1"), _case("CASE-2", "TP-2")],
        mutated_cases=[_case("CASE-1", "TP-1")],
        reviewer_output=GeneratedReviewerOutput(missing_test_point_ids=["TP-2"]),
        supplemental_cases=[_case("CASE-3", "TP-2")],
        final_cases=[_case("CASE-1", "TP-1"), _case("CASE-3", "TP-2")],
        final_status="READY",
        mutation=_mutation(),
    )

    report = grade_recovery(sample)

    assert report["detection_rate"]["value"] == 1.0
    assert report["supplement_target_recall"]["value"] == 1.0
    assert report["coverage_recovery"]["value"] == 1.0
    assert report["repair_success"] is True


def test_recovery_grader_prefers_initial_reviewer_output_before_local_validation():
    sample = RecoveryEvalSample(
        sample_id="sample-initial-review",
        operation_id="op-1",
        variant="recovery_mutation",
        reviewer_initial_output=GeneratedReviewerOutput(),
        reviewer_initial_suggested_test_point_ids=["TP-2"],
        reviewer_output=GeneratedReviewerOutput(),
        supplemental_cases=[_case("CASE-3", "TP-2")],
        final_cases=[_case("CASE-3", "TP-2")],
        final_status="READY",
        mutation=_mutation(),
    )

    report = grade_recovery(sample)

    assert report["detection_rate"]["value"] == 1.0


def test_recovery_grader_does_not_count_unexpected_supplement_as_recovery():
    sample = RecoveryEvalSample(
        sample_id="sample-2",
        operation_id="op-1",
        variant="recovery_mutation",
        original_cases=[_case("CASE-2", "TP-2")],
        mutated_cases=[],
        reviewer_output=GeneratedReviewerOutput(missing_test_point_ids=["TP-2"]),
        supplemental_cases=[_case("CASE-3", "TP-OTHER")],
        final_cases=[_case("CASE-3", "TP-OTHER")],
        final_status="READY",
        mutation=_mutation(),
    )

    report = grade_recovery(sample)

    assert report["supplement_target_recall"]["value"] == 0.0
    assert report["coverage_recovery"]["value"] == 0.0
    assert report["unexpected_supplement_test_point_ids"] == ["TP-OTHER"]
    assert report["repair_success"] is False


def test_recovery_aggregate_reports_clean_control_alarm_rate():
    control = RecoveryEvalSample(
        sample_id="control",
        operation_id="op-1",
        variant="recovery_control",
        reviewer_output=GeneratedReviewerOutput(),
        supplemental_cases=[],
        final_status="READY",
    )
    mutation = RecoveryEvalSample(
        sample_id="mutation",
        operation_id="op-1",
        variant="recovery_mutation",
        reviewer_output=GeneratedReviewerOutput(missing_test_point_ids=["TP-2"]),
        supplemental_cases=[_case("CASE-3", "TP-2")],
        final_cases=[_case("CASE-3", "TP-2")],
        final_status="READY",
        mutation=_mutation(),
    )

    summary = aggregate_recovery([control, mutation])

    assert summary["mutation_count"] == 1
    assert summary["control_count"] == 1
    assert summary["detection_rate"]["value"] == 1.0
    assert summary["recovery_rate"]["value"] == 1.0
    assert summary["clean_control_alarm_rate"]["value"] == 0.0

def _runtime_cases() -> CaseSet:
    return CaseSet(
        requirement_id="REQ-1",
        test_point_ids=["TP-1"],
        cases=[
            BackendTestCase(
                case_id="CASE-1",
                requirement_id="REQ-1",
                test_point_ids=["TP-1"],
                title="查询成功",
                category="positive",
                steps=["发送请求"],
                expected_behavior="返回成功",
                request=RequestTemplate(
                    method="GET",
                    path="/items/{id}",
                    path_params={"id": 1},
                    headers={"Authorization": "<redacted>"},
                ),
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


def test_recovery_mutation_runtime_supports_parameter_assertion_and_auth_defects():
    original = _runtime_cases()
    path_mutation = RecoveryMutationSpec(
        mutation_id="path-param:CASE-1",
        kind="remove_required_path_param",
        target_case_id="CASE-1",
        target_test_point_ids=["TP-1"],
        target_parameter_name="id",
        description="remove required path parameter",
    )
    assertion_mutation = RecoveryMutationSpec(
        mutation_id="assertions:CASE-1",
        kind="remove_all_assertions",
        target_case_id="CASE-1",
        target_test_point_ids=["TP-1"],
        description="remove assertions",
    )
    auth_mutation = RecoveryMutationSpec(
        mutation_id="auth:CASE-1",
        kind="remove_auth_header",
        target_case_id="CASE-1",
        target_test_point_ids=["TP-1"],
        target_header_name="Authorization",
        description="remove auth header",
    )

    path_cases = mutate_recovery_cases(original, path_mutation)
    assertion_cases = mutate_recovery_cases(original, assertion_mutation)
    auth_cases = mutate_recovery_cases(original, auth_mutation)

    assert path_cases.cases[0].request.path_params == {}
    assert assertion_cases.cases[0].assertions == []
    assert auth_cases.cases[0].request.headers == {}
    assert original.cases[0].request.path_params == {"id": 1}
    assert len(original.cases[0].assertions) == 1
    assert original.cases[0].request.headers == {"Authorization": "<redacted>"}


def test_recovery_grader_requires_structural_defect_repair():
    mutation = RecoveryMutationSpec(
        mutation_id="path-param:CASE-1",
        kind="remove_required_path_param",
        target_case_id="CASE-1",
        target_test_point_ids=["TP-1"],
        target_parameter_name="id",
        description="remove required path parameter",
    )
    final_case = GeneratedCase(
        case_id="CASE-1",
        test_point_ids=["TP-1"],
        request={"path_params": {"id": 1}},
    )
    not_repaired = final_case.model_copy(update={"request": {"path_params": {}}})
    sample = RecoveryEvalSample(
        sample_id="structural-repair",
        operation_id="op-1",
        variant="recovery_mutation",
        final_cases=[not_repaired],
        final_status="READY",
        mutation=mutation,
    )

    report = grade_recovery(sample)

    assert report["coverage_recovery"]["value"] == 1.0
    assert report["defect_recovered"] is False
    assert report["repair_success"] is False


def test_recovery_suite_validation_accepts_explicit_operation_id_alias():
    control = RecoveryEvalSample(
        sample_id="control-legacy",
        operation_id="op-legacy",
        variant="recovery_control",
    )
    mutation = RecoveryEvalSample(
        sample_id="mutation-legacy",
        operation_id="op-legacy",
        variant="recovery_mutation",
        mutation=_mutation(),
    )

    result = validate_recovery_suite(
        [control, mutation],
        {"op-1"},
        operation_id_aliases={"op-legacy": "op-1"},
    )

    assert result["status"] == "ready"
    assert result["observed_operation_ids"] == ["op-1"]
    assert result["alias_resolutions"] == {"op-legacy": "op-1"}


def test_recovery_suite_validation_rejects_duplicate_controls():
    control = RecoveryEvalSample(
        sample_id="control-1",
        operation_id="op-1",
        variant="recovery_control",
    )
    duplicate = control.model_copy(update={"sample_id": "control-2"})

    result = validate_recovery_suite([control, duplicate], {"op-1"})

    assert result["status"] == "pending_input"
    assert any(issue["type"] == "control_count_invalid" for issue in result["issues"])


def _ready_recovery_report(rate: float) -> dict:
    numerator = int(round(rate * 10))
    metric_names = [
        "recovery_rate",
        "defect_recovery_rate",
        "detection_rate",
        "supplement_target_recall",
        "repair_success_rate",
        "final_validator_pass_rate",
    ]
    summary = {
        "status": "ready",
        "clean_control_alarm_rate": {"value": 0.0, "numerator": 0, "denominator": 1},
    }
    for name in metric_names:
        summary[name] = {"value": rate, "numerator": numerator, "denominator": 10}
    return {
        "status": "ready",
        "dataset_id": "recovery-demo",
        "dataset_version": "1.0.0",
        "generated_at": "2026-08-22T00:00:00+00:00",
        "source_summary": {
            "dataset_coverage_status": "ready",
            "expected_operation_ids": ["op-1"],
        },
        "recovery_summary": summary,
    }


def test_recovery_experiment_summary_reports_all_runs_and_pooled_rate(tmp_path):
    paths = []
    for index, rate in enumerate((0.9, 1.0, 0.8), start=1):
        path = tmp_path / f"run-{index}.json"
        path.write_text(json.dumps(_ready_recovery_report(rate)), encoding="utf-8")
        paths.append(path)

    report = build_experiment_report(paths)

    assert report["run_count"] == 3
    assert report["all_runs_meet_threshold"] is False
    assert report["mean_meets_threshold"] is True
    assert report["metrics"]["coverage_recovery_rate"]["pooled"]["value"] == 0.9
