from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from evals.dataset import load_manifest
from evals.models import EvalDatasetManifest, EvalSample, GroundTruthOperation
from evals.runner import load_samples


def validate_pilot_annotations(operation: GroundTruthOperation, sample: EvalSample) -> None:
    generated_point_ids = {point.point_id for point in sample.test_points}
    annotated_point_ids = [item.generated_point_id for item in sample.annotations.point_matches]
    if len(annotated_point_ids) != len(set(annotated_point_ids)):
        raise ValueError("generated Test Point annotations contain duplicates")
    if generated_point_ids != set(annotated_point_ids):
        raise ValueError("every generated Test Point must have exactly one annotation")

    ground_truth_point_ids = {point.point_id for point in operation.points}
    unknown_point_matches = {
        item.ground_truth_point_id
        for item in sample.annotations.point_matches
        if item.ground_truth_point_id is not None
        and item.ground_truth_point_id not in ground_truth_point_ids
    }
    if unknown_point_matches:
        raise ValueError(f"point annotations reference unknown Ground Truth: {unknown_point_matches}")

    required_assertion_ids = {
        assertion.assertion_id
        for point in operation.points
        for assertion in point.required_assertions
        if assertion.required
    }
    mapped_assertion_ids = {
        item.ground_truth_assertion_id for item in sample.annotations.assertion_matches
    }
    missing_assertions = required_assertion_ids - mapped_assertion_ids
    if missing_assertions:
        raise ValueError(f"required Ground Truth assertions are not mapped: {missing_assertions}")

    generated_assertions = {
        (case.case_id, assertion.assertion_id)
        for case in sample.cases
        for assertion in case.assertions
    }
    unknown_generated_assertions = {
        (item.case_id, item.generated_assertion_id)
        for item in sample.annotations.assertion_matches
        if (item.case_id, item.generated_assertion_id) not in generated_assertions
    }
    if unknown_generated_assertions:
        raise ValueError(
            f"assertion annotations reference unknown generated assertions: {unknown_generated_assertions}"
        )


def build_verified_pilot(
    manifest: EvalDatasetManifest,
    sample: EvalSample,
    operation_id: str,
) -> EvalDatasetManifest:
    operation = next(
        (item for item in manifest.operations if item.operation_id == operation_id),
        None,
    )
    if operation is None:
        raise ValueError(f"operation not found in manifest: {operation_id}")
    if sample.operation_id != operation_id:
        raise ValueError("sample operation_id does not match pilot operation")
    validate_pilot_annotations(operation, sample)
    verified_operation = operation.model_copy(update={"annotation_status": "verified"})
    return EvalDatasetManifest(
        dataset_id=f"{manifest.dataset_id}-{operation_id}-pilot",
        version=f"{manifest.version}-pilot.1",
        source=manifest.source,
        annotation_status="verified",
        operations=[verified_operation],
        notes=(
            f"Verified single-operation pilot extracted from {manifest.dataset_id}; "
            "the full baseline manifest remains draft."
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="从全量 draft 清单生成单接口 verified pilot")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-ground-truth",
        action="store_true",
        help="确认该接口 Ground Truth 已独立核验，不是由生成结果自证",
    )
    args = parser.parse_args()
    if not args.confirm_ground_truth:
        raise ValueError("verified pilot requires explicit --confirm-ground-truth")
    manifest = load_manifest(args.dataset)
    samples, _ = load_samples(args.input, require_redacted=True)
    if len(samples) != 1:
        raise ValueError("pilot requires exactly one base EvalSample")
    pilot = build_verified_pilot(manifest, samples[0], args.operation_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(pilot.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(
        yaml.safe_dump(
            {
                "status": "verified",
                "dataset_id": pilot.dataset_id,
                "operation_id": args.operation_id,
                "points": len(pilot.operations[0].points),
                "output": str(args.output),
            },
            allow_unicode=True,
            sort_keys=False,
        ).strip()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
