from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.recovery.models import RecoveryEvalSample
from evals.recovery_runner import (
    _validate_inputs,
    load_workflow_snapshot,
    run_recovery_sample,
    write_redacted_results,
)
from evals.environment import hydrate_environment_from_project_config
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
    sample,
    plan: dict[str, Any],
    snapshot_roots: list[Path],
) -> tuple[Path, Any]:
    errors: list[str] = []
    for data_root, snapshot in _snapshot_candidates(snapshot_roots, sample.operation_id):
        try:
            _validate_inputs(snapshot, sample, plan)
        except Exception as exc:
            errors.append(str(exc))
            continue
        return data_root, snapshot
    details = "; ".join(errors) or "no matching workflow snapshot"
    raise ValueError(f"no usable recovery snapshot for {sample.operation_id}: {details}")


def run(
    *,
    base_samples_path: Path,
    plan_root: Path,
    snapshot_roots: list[Path],
    output_root: Path,
    dry_run: bool = False,
) -> int:
    loaded_environment_refs = hydrate_environment_from_project_config(snapshot_roots)
    if loaded_environment_refs:
        print(
            json.dumps(
                {"loaded_user_environment_refs": loaded_environment_refs},
                ensure_ascii=False,
            )
        )
    base_samples, _ = load_samples(base_samples_path, require_redacted=True)
    output_root.mkdir(parents=True, exist_ok=True)
    result_root = output_root / "per-operation"
    all_samples: list[RecoveryEvalSample] = []
    summary: list[dict[str, Any]] = []

    for base_sample in base_samples:
        plan_path = plan_root / "plans" / f"{base_sample.operation_id}.yaml"
        if not plan_path.exists():
            summary.append(
                {
                    "operation_id": base_sample.operation_id,
                    "status": "pending_input",
                    "reason": "no recovery plan; private Draft Snapshot is unavailable",
                }
            )
            continue
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        data_root, snapshot = _select_snapshot(base_sample, plan, snapshot_roots)
        mutation = _validate_inputs(snapshot, base_sample, plan)
        if dry_run:
            summary.append(
                {
                    "operation_id": base_sample.operation_id,
                    "status": "validated",
                    "mutation_id": mutation.mutation_id,
                    "target_test_point_ids": mutation.target_test_point_ids,
                    "data_root": str(data_root),
                }
            )
            continue
        control = run_recovery_sample(
            snapshot=snapshot,
            base_sample=base_sample,
            plan=plan,
            data_dir=data_root,
            mutation=None,
        )
        mutated = run_recovery_sample(
            snapshot=snapshot,
            base_sample=base_sample,
            plan=plan,
            data_dir=data_root,
            mutation=mutation,
        )
        results = [control, mutated]
        result_path = result_root / f"{base_sample.operation_id}-recovery-results-redacted.json"
        write_redacted_results(result_path, results)
        all_samples.extend(results)
        summary.append(
            {
                "operation_id": base_sample.operation_id,
                "status": "completed",
                "samples": len(results),
                "mutation_id": mutation.mutation_id,
                "result": str(result_path),
            }
        )
        print(json.dumps(summary[-1], ensure_ascii=False))

    suite_path = output_root / "multi-operation-recovery-suite-redacted.json"
    write_redacted_results(suite_path, all_samples)
    summary_payload = {
        "status": "completed" if all(item["status"] == "completed" for item in summary) else "partial",
        "operation_count": len(summary),
        "completed_operation_count": sum(item["status"] == "completed" for item in summary),
        "sample_count": len(all_samples),
        "operations": summary,
        "suite": str(suite_path),
    }
    (output_root / "generation-summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary_payload, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 10 接口 Supplement Recovery Eval")
    parser.add_argument("--base-samples", type=Path, required=True)
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run(
        base_samples_path=args.base_samples,
        plan_root=args.plan_root,
        snapshot_roots=args.snapshot_root,
        output_root=args.output_root,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
