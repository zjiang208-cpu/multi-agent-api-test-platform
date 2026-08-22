from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.input_audit import audit_input_payload
from evals.models import EvalSample
from evals.recovery.models import RecoveryMutationSpec
from evals.recovery.validation import operation_id_candidates
from app.workflow.prompts import WORKFLOW_PROMPT_VERSION
from evals.runner import load_samples


PROMPT_VERSION = WORKFLOW_PROMPT_VERSION


def _snapshot_case_ids(snapshot_roots: list[Path], operation_ids: list[str]) -> set[str]:
    case_ids: set[str] = set()
    for root in snapshot_roots:
        for path in root.glob("projects/*/artifacts/workflow-runs/*.yaml"):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if payload.get("operation_id") not in operation_ids:
                continue
            for case in (payload.get("draft_cases") or {}).get("cases", []):
                if case.get("case_id"):
                    case_ids.add(str(case["case_id"]))
    return case_ids


def _build_plan(
    sample: EvalSample,
    *,
    available_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    candidates = [
        case
        for case in sample.cases
        if available_case_ids is None or case.case_id in available_case_ids
    ]
    if not candidates:
        raise ValueError(f"no snapshot draft case is available: {sample.operation_id}")
    candidates = [case for case in candidates if case.test_point_ids]
    if not candidates:
        raise ValueError(f"available cases have no test point references: {sample.operation_id}")
    target_case = min(
        candidates,
        key=lambda case: (len(case.test_point_ids), case.case_id),
    )
    target_points = list(dict.fromkeys(target_case.test_point_ids))
    request = target_case.request or {}
    path_params = request.get("path_params") or {}
    headers = request.get("headers") or {}
    mutations = [
        RecoveryMutationSpec(
            mutation_id=f"delete-case:{target_case.case_id}:recovery",
            kind="delete_case",
            target_case_id=target_case.case_id,
            target_test_point_ids=target_points,
            description=(
                f"删除 {target_case.case_id}，验证 Reviewer 是否发现并由 Supplement 恢复 "
                f"Test Point {target_points}。"
            ),
        )
    ]
    if path_params:
        parameter_name = sorted(path_params)[0]
        mutations.append(
            RecoveryMutationSpec(
                mutation_id=f"remove-required-path-param:{target_case.case_id}:{parameter_name}:recovery",
                kind="remove_required_path_param",
                target_case_id=target_case.case_id,
                target_test_point_ids=target_points,
                target_parameter_name=parameter_name,
                description=f"删除 {target_case.case_id} 的必填 path 参数 {parameter_name}。",
            )
        )
    if target_case.assertions:
        mutations.append(
            RecoveryMutationSpec(
                mutation_id=f"remove-all-assertions:{target_case.case_id}:recovery",
                kind="remove_all_assertions",
                target_case_id=target_case.case_id,
                target_test_point_ids=target_points,
                description=f"删除 {target_case.case_id} 的全部断言，制造不可验收用例。",
            )
        )
    auth_header = next(
        (name for name in headers if name.lower() == "authorization"),
        None,
    )
    if auth_header is not None:
        mutations.append(
            RecoveryMutationSpec(
                mutation_id=f"remove-auth-header:{target_case.case_id}:recovery",
                kind="remove_auth_header",
                target_case_id=target_case.case_id,
                target_test_point_ids=target_points,
                target_header_name=auth_header,
                description=f"删除 {target_case.case_id} 的鉴权头 {auth_header}。",
            )
        )
    return {
        "operation_id": sample.operation_id,
        "base_sample": sample.sample_id,
        "prompt_version": PROMPT_VERSION,
        "status": "prepared_for_recovery_run",
        "notes": (
            "Recovery 对同一目标 Case 注入删除 Case、缺失路径参数、缺失断言和缺失鉴权头等"
            "可导致覆盖缺口的故障；每种 Mutation 独立运行。"
        ),
        "mutation_count": len(mutations),
        # 保留 mutation 字段兼容旧版单 Mutation Runner。
        "mutation": mutations[0].model_dump(mode="json"),
        "mutations": [mutation.model_dump(mode="json") for mutation in mutations],
    }


def build(
    input_path: Path,
    output_root: Path,
    *,
    snapshot_roots: list[Path],
    operation_id_aliases: dict[str, str] | None = None,
) -> int:
    samples, _ = load_samples(input_path, require_redacted=True)
    output_root.mkdir(parents=True, exist_ok=True)
    plans_dir = output_root / "plans"
    bases_dir = output_root / "bases"
    plans_dir.mkdir(parents=True, exist_ok=True)
    bases_dir.mkdir(parents=True, exist_ok=True)

    operations: list[dict[str, Any]] = []
    for sample in samples:
        available = _snapshot_case_ids(
            snapshot_roots,
            operation_id_candidates(sample.operation_id, operation_id_aliases),
        )
        if not available:
            operations.append(
                {
                    "operation_id": sample.operation_id,
                    "status": "pending_input",
                    "reason": "no private workflow snapshot with draft_cases",
                }
            )
            continue
        plan = _build_plan(sample, available_case_ids=available)
        plan_path = plans_dir / f"{sample.operation_id}.yaml"
        base_path = bases_dir / f"{sample.operation_id}-base-redacted.json"
        plan_path.write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        payload = {"samples": [sample.model_dump(mode="json")]}
        audit = audit_input_payload(payload)
        if audit["status"] != "ready":
            raise ValueError(f"recovery base failed redaction audit: {sample.operation_id}")
        base_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        operations.append(
            {
                "operation_id": sample.operation_id,
                "status": "prepared",
                "mutation_count": plan["mutation_count"],
                "plan": str(plan_path),
                "base": str(base_path),
            }
        )

    summary = {
        "status": "prepared",
        "input": str(input_path),
        "prompt_version": PROMPT_VERSION,
        "operations": operations,
    }
    (output_root / "generation-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Supplement Recovery 脱敏输入计划")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, action="append", required=True)
    parser.add_argument("--operation-aliases", type=Path)
    args = parser.parse_args()
    aliases = {}
    if args.operation_aliases:
        payload = yaml.safe_load(args.operation_aliases.read_text(encoding="utf-8")) or {}
        aliases = payload.get("operation_id_aliases", payload) if isinstance(payload, dict) else {}
    return build(
        args.input,
        args.output_root,
        snapshot_roots=args.snapshot_root,
        operation_id_aliases={str(key): str(value) for key, value in aliases.items()},
    )


if __name__ == "__main__":
    raise SystemExit(main())
