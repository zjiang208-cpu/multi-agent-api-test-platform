from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.recovery.models import RecoveryEvalSample
from evals.recovery_runner import (
    _load_operation_aliases,
    _validate_inputs,
    load_workflow_snapshot,
    run_recovery_sample,
    write_redacted_results,
)
from evals.environment import hydrate_environment_from_project_config
from evals.recovery.validation import operation_id_candidates
from evals.runner import load_samples


def _snapshot_candidates(
    snapshot_roots: list[Path], operation_ids: list[str]
) -> list[tuple[Path, Any]]:
    candidates: list[tuple[Path, Any]] = []
    for root in snapshot_roots:
        for path in root.glob("projects/*/artifacts/workflow-runs/*.yaml"):
            snapshot = load_workflow_snapshot(path)
            if snapshot.operation_id in operation_ids:
                candidates.append((root, snapshot))
    return candidates


def _select_snapshot(
    sample,
    plan: dict[str, Any],
    snapshot_roots: list[Path],
    operation_id_aliases: dict[str, str] | None = None,
) -> tuple[Path, Any]:
    errors: list[str] = []
    operation_ids = operation_id_candidates(sample.operation_id, operation_id_aliases)
    for data_root, snapshot in _snapshot_candidates(snapshot_roots, operation_ids):
        try:
            _validate_inputs(
                snapshot,
                sample,
                plan,
                operation_id_aliases=operation_id_aliases,
            )
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
    operation_id_aliases: dict[str, str] | None = None,
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
        plan_path = next(
            (
                plan_root / "plans" / f"{operation_id}.yaml"
                for operation_id in operation_id_candidates(
                    base_sample.operation_id,
                    operation_id_aliases,
                )
                if (plan_root / "plans" / f"{operation_id}.yaml").exists()
            ),
            None,
        )
        if plan_path is None:
            summary.append(
                {
                    "operation_id": base_sample.operation_id,
                    "status": "pending_input",
                    "reason": "no recovery plan; private Draft Snapshot is unavailable",
                }
            )
            continue
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        data_root, snapshot = _select_snapshot(
            base_sample,
            plan,
            snapshot_roots,
            operation_id_aliases,
        )
        raw_mutations = plan.get("mutations") or [plan.get("mutation")]
        mutation_plans = [
            {**plan, "mutation": raw_mutation}
            for raw_mutation in raw_mutations
            if raw_mutation
        ]
        mutations = [
            _validate_inputs(
                snapshot,
                base_sample,
                mutation_plan,
                operation_id_aliases=operation_id_aliases,
            )
            for mutation_plan in mutation_plans
        ]
        if not mutations:
            raise ValueError(f"recovery plan has no mutations: {base_sample.operation_id}")
        if dry_run:
            summary.append(
                {
                    "operation_id": base_sample.operation_id,
                    "status": "validated",
                    "mutation_count": len(mutations),
                    "mutation_ids": [mutation.mutation_id for mutation in mutations],
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
        results = [control]
        for mutation in mutations:
            mutation_plan = {
                **plan,
                "mutation": mutation.model_dump(mode="json"),
            }
            results.append(
                run_recovery_sample(
                    snapshot=snapshot,
                    base_sample=base_sample,
                    plan=mutation_plan,
                    data_dir=data_root,
                    mutation=mutation,
                    operation_id_aliases=operation_id_aliases,
                )
            )
        result_path = result_root / f"{base_sample.operation_id}-recovery-results-redacted.json"
        write_redacted_results(result_path, results)
        all_samples.extend(results)
        summary.append(
            {
                "operation_id": base_sample.operation_id,
                "status": "completed",
                "samples": len(results),
                "mutation_count": len(mutations),
                "mutation_ids": [mutation.mutation_id for mutation in mutations],
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
    parser.add_argument("--operation-aliases", type=Path)
    args = parser.parse_args()
    return run(
        base_samples_path=args.base_samples,
        plan_root=args.plan_root,
        snapshot_roots=args.snapshot_root,
        output_root=args.output_root,
        operation_id_aliases=_load_operation_aliases(args.operation_aliases),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
