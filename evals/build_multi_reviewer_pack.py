from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.input_audit import audit_input_payload
from evals.models import EvalSample
from evals.mutations.build_pack import build_reviewer_mutation_pack
from evals.runner import load_samples


PROMPT_VERSION = "nlu:1.5.8|designer:1.5.8|reviewer:1.3.8"


def _snapshot_case_ids(snapshot_roots: list[Path], operation_id: str) -> set[str]:
    case_ids: set[str] = set()
    for root in snapshot_roots:
        for path in root.glob("projects/*/artifacts/workflow-runs/*.yaml"):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if payload.get("operation_id") != operation_id:
                continue
            draft_cases = payload.get("draft_cases") or {}
            case_ids.update(
                str(case.get("case_id"))
                for case in draft_cases.get("cases", [])
                if case.get("case_id")
            )
    return case_ids


def _mutation_plan(
    sample: EvalSample,
    *,
    available_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not sample.cases:
        raise ValueError(f"operation has no generated cases: {sample.operation_id}")

    candidate_cases = [
        case
        for case in sample.cases
        if available_case_ids is None or case.case_id in available_case_ids
    ]
    if not candidate_cases:
        raise ValueError(
            f"no generated cases are present in the workflow snapshot: {sample.operation_id}"
        )
    first_case = candidate_cases[0]
    delete_case = candidate_cases[-1]
    assertion_case = next((case for case in candidate_cases if case.assertions), None)
    if assertion_case is None:
        raise ValueError(f"operation has no generated assertions: {sample.operation_id}")

    mutations: list[dict[str, Any]] = [
        {
            "mutation_id": f"delete-case:{delete_case.case_id}",
            "kind": "delete_case",
            "target_case_id": delete_case.case_id,
            "reviewer_field": "missing_test_point_ids",
            "target_ids": delete_case.test_point_ids,
            "description": f"删除 {delete_case.case_id}，制造测试点覆盖缺口。",
        },
        {
            "mutation_id": f"duplicate-case:{first_case.case_id}",
            "kind": "duplicate_case",
            "target_case_id": first_case.case_id,
            "reviewer_field": "duplicate_case_ids",
            "target_ids": [first_case.case_id, f"{first_case.case_id}__duplicate"],
            "target_match": "any",
            "description": f"复制 {first_case.case_id}，制造重复用例。",
        },
        {
            "mutation_id": (
                f"unsupported-assertion-path:{assertion_case.case_id}:"
                f"{assertion_case.assertions[0].assertion_id}"
            ),
            "kind": "unsupported_assertion_path",
            "target_case_id": assertion_case.case_id,
            "target_assertion_id": assertion_case.assertions[0].assertion_id,
            "path": "$.data[*].id",
            "reviewer_field": "unsupported_assertion_ids",
            "target_ids": [assertion_case.assertions[0].assertion_id],
            "description": (
                f"将 {assertion_case.case_id} 的断言改成执行器不支持的通配符路径。"
            ),
        },
    ]

    path_case = next(
        (case for case in candidate_cases if case.request.get("path_params")),
        None,
    )
    if path_case is not None:
        parameter_name = next(iter(path_case.request["path_params"]))
        mutations.append(
            {
                "mutation_id": (
                    f"remove-required-path-param:{path_case.case_id}:{parameter_name}"
                ),
                "kind": "remove_required_path_param",
                "target_case_id": path_case.case_id,
                "target_parameter_name": parameter_name,
                "reviewer_field": "invalid_case_ids",
                "target_ids": [path_case.case_id],
                "description": (
                    f"删除 {path_case.case_id} 的 path 参数 {parameter_name}，"
                    "制造不可执行请求。"
                ),
            }
        )

    return {
        "operation_id": sample.operation_id,
        "base_sample": sample.sample_id,
        "prompt_version": PROMPT_VERSION,
        "status": "prepared_for_reviewer_run",
        "notes": (
            "按接口实际生成结果选择适用 Mutation。所有接口至少验证删除用例、"
            "重复用例和不支持断言路径；存在 path 参数时额外验证缺失必填 path 参数。"
        ),
        "mutations": mutations,
    }


def build(
    input_path: Path,
    output_root: Path,
    operation_ids: list[str] | None = None,
    snapshot_roots: list[Path] | None = None,
) -> int:
    samples, _ = load_samples(input_path, require_redacted=True)
    selected = [
        sample
        for sample in samples
        if operation_ids is None or sample.operation_id in operation_ids
    ]
    if not selected:
        raise ValueError("no matching operation samples")

    plans_dir = output_root / "plans"
    bases_dir = output_root / "bases"
    packs_dir = output_root / "packs"
    plans_dir.mkdir(parents=True, exist_ok=True)
    bases_dir.mkdir(parents=True, exist_ok=True)
    packs_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    for sample in selected:
        available_case_ids = (
            _snapshot_case_ids(snapshot_roots or [], sample.operation_id)
            if snapshot_roots
            else None
        )
        plan = _mutation_plan(
            sample,
            available_case_ids=available_case_ids or None,
        )
        base_path = bases_dir / f"{sample.operation_id}-base-redacted.json"
        plan_path = plans_dir / f"{sample.operation_id}.yaml"
        pack_path = packs_dir / f"{sample.operation_id}-mutations-redacted.json"
        base_path.write_text(
            json.dumps({"samples": [sample.model_dump(mode="json")]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        plan_path.write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        mutations = build_reviewer_mutation_pack(sample, plan)
        payload = {"samples": [item.model_dump(mode="json") for item in mutations]}
        audit = audit_input_payload(payload)
        if audit["status"] != "ready":
            raise ValueError(f"mutation pack failed redaction audit: {sample.operation_id}")
        pack_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary.append(
            {
                "operation_id": sample.operation_id,
                "case_count": len(sample.cases),
                "mutation_count": len(mutations),
                "base": str(base_path),
                "plan": str(plan_path),
                "pack": str(pack_path),
            }
        )

    summary_path = output_root / "generation-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "prepared",
                "input": str(input_path),
                "operations": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"status": "prepared", "operations": summary}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="为全量接口生成 Reviewer Mutation 脱敏输入包")
    parser.add_argument("--input", type=Path, required=True, help="全量脱敏 EvalSample JSON")
    parser.add_argument("--output-root", type=Path, required=True, help="本地忽略输出目录")
    parser.add_argument("--operation", action="append", help="只生成指定 operation_id，可重复")
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        action="append",
        help="Workflow 快照私有目录，可重复；用于选择快照中实际存在的草稿 Case",
    )
    args = parser.parse_args()
    return build(args.input, args.output_root, args.operation, args.snapshot_root)


if __name__ == "__main__":
    raise SystemExit(main())
