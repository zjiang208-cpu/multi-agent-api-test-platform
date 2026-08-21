from evals.graders.recovery import aggregate_recovery, grade_recovery
from evals.models import GeneratedCase, GeneratedReviewerOutput
from evals.recovery.models import RecoveryEvalSample, RecoveryMutationSpec


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
