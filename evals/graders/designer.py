from __future__ import annotations

import re
from typing import Any

from evals.graders.common import annotation_pending, case_fingerprint, ratio
from evals.models import EvalSample, GroundTruthOperation, GeneratedCase


SUPPORTED_ASSERTIONS = {
    "status_code",
    "json_value",
    "json_type",
    "json_contains",
    "json_exists",
    "json_array_sorted",
    "header_value",
    "response_schema",
    "response_time_ms",
}
JSON_PATH = re.compile(r"^\$(?:\.[^\.\[\]]+|\[\d+\])*$")


def _structural_case_errors(case: GeneratedCase, known_points: set[str]) -> list[str]:
    errors: list[str] = []
    if not case.test_point_ids:
        errors.append("case has no test point references")
    if set(case.test_point_ids) - known_points:
        errors.append("case references unknown test point")
    if not case.request.get("method") or not str(case.request.get("path", "")).startswith("/"):
        errors.append("request method/path is invalid")
    if not case.assertions:
        errors.append("case has no assertions")
    assertion_ids: set[str] = set()
    for assertion in case.assertions:
        if assertion.assertion_id in assertion_ids:
            errors.append("case has duplicate assertion IDs")
        assertion_ids.add(assertion.assertion_id)
        if assertion.type not in SUPPORTED_ASSERTIONS:
            errors.append(f"unsupported assertion: {assertion.type}")
        if assertion.type.startswith("json_") and (
            not assertion.path or not JSON_PATH.fullmatch(assertion.path)
        ):
            errors.append(f"invalid JSON path: {assertion.assertion_id}")
    return errors


def _case_errors(case: GeneratedCase, sample: EvalSample) -> list[str]:
    if case.executable is not None:
        return list(case.executable_errors) if not case.executable else []
    if sample.operation is not None:
        try:
            from app.cases.validator import validate_case
            from app.models.cases import TestCase
            from app.models.contracts import OperationContract

            # EvalSample 的 GeneratedCase 还带有评测元字段；业务 TestCase 不接收这两个字段。
            typed_case = TestCase.model_validate(
                case.model_dump(exclude={"executable", "executable_errors"})
            )
            operation = OperationContract.model_validate(sample.operation)
            return validate_case(
                typed_case,
                known_test_points={point.point_id for point in sample.test_points},
                known_evidence=set(sample.known_evidence_ids),
                operation=operation,
            )
        except (ImportError, TypeError, ValueError) as exc:
            return [f"typed validator unavailable: {type(exc).__name__}"]
    return _structural_case_errors(case, {point.point_id for point in sample.test_points})


def grade_designer(
    operation: GroundTruthOperation,
    sample: EvalSample,
    *,
    dataset_status: str,
) -> dict[str, Any]:
    pending_reason = annotation_pending(dataset_status, operation.annotation_status)
    point_map = {
        match.generated_point_id: match.ground_truth_point_id
        for match in sample.annotations.point_matches
        if match.ground_truth_point_id
    }
    ground_truth_ids = {point.point_id for point in operation.points}
    observation_point_ids = {
        point.point_id
        for point in operation.points
        if point.verification_mode == "observation"
    }
    response_point_ids = ground_truth_ids - observation_point_ids
    covered = {
        point_map[generated_id]
        for case in sample.cases
        for generated_id in case.test_point_ids
        if generated_id in point_map and point_map[generated_id] in ground_truth_ids
    }
    covered_observations = covered & observation_point_ids
    required_assertions = {
        assertion.assertion_id
        for point in operation.points
        for assertion in point.required_assertions
        if assertion.required
    }
    matched_assertions = {
        match.ground_truth_assertion_id
        for match in sample.annotations.assertion_matches
        if match.ground_truth_assertion_id in required_assertions
    }
    executable_errors = {
        case.case_id: _case_errors(case, sample)
        for case in sample.cases
    }
    executable_count = sum(not errors for errors in executable_errors.values())
    fingerprints = [case_fingerprint(case) for case in sample.cases]
    duplicate_count = len(fingerprints) - len(set(fingerprints))
    return {
        "generated_cases": len(sample.cases),
        "covered_ground_truth_points": len(covered),
        "observation_ground_truth_points": len(observation_point_ids),
        "response_ground_truth_points": len(response_point_ids),
        "covered_observation_points": len(covered_observations),
        "covered_response_points": len(covered & response_point_ids),
        "required_assertions": len(required_assertions),
        "matched_required_assertions": len(matched_assertions),
        "duplicate_cases": duplicate_count,
        "non_executable_cases": {
            case_id: errors for case_id, errors in executable_errors.items() if errors
        },
        "test_point_coverage": ratio(
            len(covered),
            len(ground_truth_ids),
            pending_reason=pending_reason,
        ),
        "response_test_point_coverage": ratio(
            len(covered & response_point_ids),
            len(response_point_ids),
            pending_reason=pending_reason,
        ),
        "observation_coverage": ratio(
            len(covered_observations),
            len(observation_point_ids),
            pending_reason=pending_reason,
        ),
        "assertion_coverage": ratio(
            len(matched_assertions),
            len(required_assertions),
            pending_reason=pending_reason,
        ),
        "executable_case_rate": ratio(
            executable_count,
            len(sample.cases),
        ),
        "duplicate_rate": ratio(
            duplicate_count,
            len(sample.cases),
            pending_reason=None,
        ),
    }


def aggregate_designer(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总 Designer 的必要断言覆盖率，使用跨接口 Micro Average。"""

    ready_reports = [report for report in reports if report]
    required_assertions = sum(
        int(report.get("required_assertions", 0)) for report in ready_reports
    )
    matched_required_assertions = sum(
        int(report.get("matched_required_assertions", 0))
        for report in ready_reports
    )
    return {
        "status": "ready" if ready_reports else "pending_input",
        "sample_count": len(ready_reports),
        "required_assertions": required_assertions,
        "matched_required_assertions": matched_required_assertions,
        "assertion_coverage": ratio(
            matched_required_assertions,
            required_assertions,
        ),
    }
