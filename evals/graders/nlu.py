from __future__ import annotations

from typing import Any

from evals.graders.common import annotation_pending, ratio
from evals.models import EvalSample, GroundTruthOperation


def grade_nlu(
    operation: GroundTruthOperation,
    sample: EvalSample,
    *,
    dataset_status: str,
) -> dict[str, Any]:
    pending_reason = annotation_pending(dataset_status, operation.annotation_status)
    ground_truth_ids = {point.point_id for point in operation.points}
    observation_ids = {
        point.point_id
        for point in operation.points
        if point.verification_mode == "observation"
    }
    response_ids = ground_truth_ids - observation_ids
    matches = sample.annotations.point_matches
    generated_ids = {point.point_id for point in sample.test_points}
    matched = {
        match.ground_truth_point_id
        for match in matches
        if match.ground_truth_point_id in ground_truth_ids and match.generated_point_id in generated_ids
    }
    supported = {
        match.generated_point_id
        for match in matches
        if match.supported and match.generated_point_id in generated_ids
    }
    annotations_complete = len(matches) == len(generated_ids) and all(
        match.generated_point_id in generated_ids for match in matches
    )
    quality_pending = pending_reason or (
        None if annotations_complete else "point_matches must cover every generated test point"
    )
    return {
        "generated_test_points": len(generated_ids),
        "ground_truth_test_points": len(ground_truth_ids),
        "response_ground_truth_points": len(response_ids),
        "observation_ground_truth_points": len(observation_ids),
        "matched_ground_truth_points": len(matched),
        "matched_response_points": len(matched & response_ids),
        "matched_observation_points": len(matched & observation_ids),
        "supported_generated_points": len(supported),
        "annotations_complete": annotations_complete,
        "test_point_recall": ratio(
            len(matched),
            len(ground_truth_ids),
            pending_reason=pending_reason,
        ),
        "response_test_point_recall": ratio(
            len(matched & response_ids),
            len(response_ids),
            pending_reason=pending_reason,
        ),
        "observation_test_point_recall": ratio(
            len(matched & observation_ids),
            len(observation_ids),
            pending_reason=pending_reason,
        ),
        "test_point_precision": ratio(
            len(supported),
            len(generated_ids),
            pending_reason=quality_pending,
        ),
        "hallucination_rate": ratio(
            len(generated_ids - supported),
            len(generated_ids),
            pending_reason=quality_pending,
        ),
    }
