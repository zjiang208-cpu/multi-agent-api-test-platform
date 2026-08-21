from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.models import EvalSample
from evals.reviewer_runner import (
    load_workflow_snapshot,
    run_reviewer_control,
    run_reviewer_mutations,
    validate_inputs,
    write_redacted_results,
)
from evals.runner import load_samples


def _snapshot_candidates(
    snapshot_roots: list[Path], operation_id: str
) -> list[tuple[Path, Any]]:
    candidates: list[tuple[Path, Any]] = []
    for root in snapshot_roots:
        for path in root.glob("projects/*/artifacts/workflow-runs/*.yaml"):
            snapshot = load_workflow_snapshot(path)
            if snapshot.operation_id == operation_id:
                candidates.append((root, snapshot))
    return candidates


def _select_snapshot(
    sample: EvalSample,
    plan: dict[str, Any],
    snapshot_roots: list[Path],
) -> tuple[Path, Any]:
    errors: list[str] = []
    for data_root, snapshot in _snapshot_candidates(snapshot_roots, sample.operation_id):
        try:
            validate_inputs(snapshot, sample, plan)
        except Exception as exc:
            errors.append(str(exc))
            continue
        return data_root, snapshot
    details = "; ".join(errors) or "no matching workflow snapshot"
    raise ValueError(f"no usable snapshot for {sample.operation_id}: {details}")


def run(
    *,
    base_samples_path: Path,
    plan_root: Path,
    snapshot_roots: list[Path],
    existing_get_shop_suite: Path,
    output_root: Path,
) -> int:
    base_samples, _ = load_samples(base_samples_path, require_redacted=True)
    base_by_operation = {sample.operation_id: sample for sample in base_samples}
    suite_samples, _ = load_samples(existing_get_shop_suite, require_redacted=True)
    if {sample.operation_id for sample in suite_samples} != {"get-shop-id"}:
        raise ValueError("existing get-shop Reviewer suite must contain only get-shop-id")

    output_root.mkdir(parents=True, exist_ok=True)
    result_root = output_root / "per-operation"
    all_samples: list[EvalSample] = list(suite_samples)
    summary: list[dict[str, Any]] = [
        {
            "operation_id": "get-shop-id",
            "status": "reused_verified_pilot_suite",
            "samples": len(suite_samples),
        }
    ]

    for operation_id, sample in base_by_operation.items():
        if operation_id == "get-shop-id":
            continue
        plan_path = plan_root / "plans" / f"{operation_id}.yaml"
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        data_root, snapshot = _select_snapshot(sample, plan, snapshot_roots)
        control = run_reviewer_control(
            snapshot=snapshot,
            base_sample=sample,
            plan=plan,
            data_dir=data_root,
        )
        mutations = run_reviewer_mutations(
            snapshot=snapshot,
            base_sample=sample,
            plan=plan,
            data_dir=data_root,
        )
        results = [control, *mutations]
        result_path = result_root / f"{operation_id}-reviewer-results-redacted.json"
        write_redacted_results(result_path, results)
        all_samples.extend(results)
        summary.append(
            {
                "operation_id": operation_id,
                "status": "completed" if all(item.reviewer_output is not None for item in results) else "partial",
                "samples": len(results),
                "mutation_count": len(mutations),
                "result": str(result_path),
            }
        )
        print(json.dumps(summary[-1], ensure_ascii=False))

    suite_path = output_root / "multi-operation-reviewer-suite-redacted.json"
    write_redacted_results(suite_path, all_samples)
    summary_path = output_root / "generation-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "completed" if all(item["status"] != "partial" for item in summary) else "partial",
                "operation_count": len(summary),
                "sample_count": len(all_samples),
                "operations": summary,
                "suite": str(suite_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "completed" if all(item["status"] != "partial" for item in summary) else "partial",
                "operation_count": len(summary),
                "sample_count": len(all_samples),
                "suite": str(suite_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运行全量接口 Reviewer Mutation 评测")
    parser.add_argument("--base-samples", type=Path, required=True)
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, action="append", required=True)
    parser.add_argument("--existing-get-shop-suite", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    return run(
        base_samples_path=args.base_samples,
        plan_root=args.plan_root,
        snapshot_roots=args.snapshot_root,
        existing_get_shop_suite=args.existing_get_shop_suite,
        output_root=args.output_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
