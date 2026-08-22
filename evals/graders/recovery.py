from __future__ import annotations

from typing import Any

from evals.graders.common import ratio
from evals.recovery.models import RecoveryEvalSample


def _point_ids(cases) -> set[str]:
    return {
        str(point_id)
        for case in cases
        for point_id in (case.test_point_ids or [])
    }


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return ratio(numerator, denominator)


def _target_points_match(found: set[str], targets: set[str], target_match: str) -> bool:
    return found == targets if target_match == "all" else bool(found & targets)


def _defect_recovered(
    sample: RecoveryEvalSample,
    targets: set[str],
    recovered: set[str],
) -> bool:
    mutation = sample.mutation
    if mutation is None or not _target_points_match(
        recovered,
        targets,
        mutation.target_match,
    ):
        return False
    if mutation.kind == "delete_case":
        return True

    target_case = next(
        (case for case in sample.final_cases if case.case_id == mutation.target_case_id),
        None,
    )
    if target_case is None:
        return False
    request = target_case.request or {}
    if mutation.kind == "remove_required_path_param":
        return str(mutation.target_parameter_name) in (request.get("path_params") or {})
    if mutation.kind == "remove_all_assertions":
        assertion_ids = {str(assertion.assertion_id) for assertion in target_case.assertions}
        return (
            str(mutation.target_assertion_id) in assertion_ids
            if mutation.target_assertion_id
            else bool(assertion_ids)
        )
    if mutation.kind == "remove_auth_header":
        headers = request.get("headers") or {}
        return any(
            str(name).lower() == str(mutation.target_header_name).lower()
            for name in headers
        )
    return False


def grade_recovery(sample: RecoveryEvalSample) -> dict[str, Any]:
    """Score detection and final quality recovery without judging free text."""

    reviewer = sample.reviewer_initial_output or sample.reviewer_output
    reviewer_detected = set(reviewer.missing_test_point_ids) if reviewer else set()
    reviewer_detected.update(
        sample.reviewer_initial_suggested_test_point_ids
        or sample.reviewer_suggested_test_point_ids
    )
    supplement_points = _point_ids(sample.supplemental_cases)
    final_points = _point_ids(sample.final_cases)

    if sample.mutation is None:
        unexpected = sorted(supplement_points)
        return {
            "status": "ready",
            "variant": "recovery_control",
            "reviewer_finding_count": (
                sum(
                    len(getattr(reviewer, field, []))
                    for field in (
                        "missing_test_point_ids",
                        "invalid_case_ids",
                        "duplicate_case_ids",
                        "unsupported_assertion_ids",
                        "semantic_gaps",
                        "remaining_gaps",
                    )
                )
                if reviewer
                else 0
            ),
            "supplement_case_count": len(sample.supplemental_cases),
            "unexpected_supplement_test_point_ids": unexpected,
            "clean_control_alarm": bool(unexpected),
            "final_validator_passed": (
                sample.final_status == "READY" and not sample.final_assembly_errors
            ),
        }

    targets = set(sample.mutation.target_test_point_ids)
    detected = reviewer_detected & targets
    supplemented = supplement_points & targets
    recovered = final_points & targets
    extras = supplement_points - targets
    final_valid = sample.final_status == "READY" and not sample.final_assembly_errors
    defect_recovered = bool(final_valid and _defect_recovered(sample, targets, recovered))
    repair_success = defect_recovered
    return {
        "status": "ready",
        "variant": "recovery_mutation",
        "mutation_id": sample.mutation.mutation_id,
        "mutation_kind": sample.mutation.kind,
        "target_test_point_ids": sorted(targets),
        "detected_test_point_ids": sorted(detected),
        "supplemented_test_point_ids": sorted(supplemented),
        "recovered_test_point_ids": sorted(recovered),
        "unexpected_supplement_test_point_ids": sorted(extras),
        "detection_rate": _metric(len(detected), len(targets)),
        "supplement_target_recall": _metric(len(supplemented), len(targets)),
        "coverage_recovery": _metric(len(recovered), len(targets)),
        "final_validator_passed": final_valid,
        "defect_recovered": defect_recovered,
        "mutation_recovery_rate": _metric(int(defect_recovered), 1),
        "repair_success": repair_success,
        "repair_success_rate": _metric(int(repair_success), 1),
    }


def aggregate_recovery(samples: list[RecoveryEvalSample]) -> dict[str, Any]:
    mutation_samples = [sample for sample in samples if sample.mutation is not None]
    controls = [sample for sample in samples if sample.mutation is None]
    reports = [grade_recovery(sample) for sample in mutation_samples]
    target_count = sum(len(report["target_test_point_ids"]) for report in reports)
    detected_count = sum(len(report["detected_test_point_ids"]) for report in reports)
    supplemented_count = sum(len(report["supplemented_test_point_ids"]) for report in reports)
    recovered_count = sum(len(report["recovered_test_point_ids"]) for report in reports)
    unexpected_count = sum(
        len(report["unexpected_supplement_test_point_ids"]) for report in reports
    )
    return {
        "status": "ready" if mutation_samples else "pending_input",
        "mutation_count": len(mutation_samples),
        "control_count": len(controls),
        "target_test_point_count": target_count,
        "detected_target_count": detected_count,
        "supplemented_target_count": supplemented_count,
        "recovered_target_count": recovered_count,
        "detection_rate": _metric(detected_count, target_count),
        "supplement_target_recall": _metric(supplemented_count, target_count),
        "recovery_rate": _metric(recovered_count, target_count),
        "defect_recovery_rate": _metric(
            sum(int(report["defect_recovered"]) for report in reports),
            len(reports),
        ),
        "repair_success_rate": _metric(
            sum(int(report["repair_success"]) for report in reports),
            len(reports),
        ),
        "final_validator_pass_rate": _metric(
            sum(int(report["final_validator_passed"]) for report in reports),
            len(reports),
        ),
        "unexpected_supplement_count": unexpected_count,
        "clean_control_alarm_rate": _metric(
            sum(int(grade_recovery(sample)["clean_control_alarm"]) for sample in controls),
            len(controls),
        ),
        "by_mutation": [
            {
                "mutation_id": report["mutation_id"],
                "kind": report["mutation_kind"],
                "detection_rate": report["detection_rate"],
                "coverage_recovery": report["coverage_recovery"],
                "defect_recovered": report["defect_recovered"],
                "repair_success": report["repair_success"],
            }
            for report in reports
        ],
    }
