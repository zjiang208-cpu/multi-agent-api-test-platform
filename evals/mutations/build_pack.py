from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.models import EvalSample
from evals.mutations.reviewer_mutations import (
    delete_case,
    duplicate_case,
    make_assertion_path_unsupported,
    remove_required_path_param,
)
from evals.runner import load_samples


def build_reviewer_mutation_pack(sample: EvalSample, plan: dict[str, Any]) -> list[EvalSample]:
    """根据脱敏计划生成 Reviewer 输入，不伪造 Reviewer 输出或变异运行 Telemetry。"""

    mutations: list[EvalSample] = []
    for entry in plan.get("mutations", []):
        kind = str(entry.get("kind") or "")
        if kind == "delete_case":
            mutated = delete_case(sample, str(entry["target_case_id"]))
        elif kind == "remove_required_path_param":
            mutated = remove_required_path_param(
                sample,
                str(entry["target_case_id"]),
                str(entry["target_parameter_name"]),
            )
        elif kind == "duplicate_case":
            mutated = duplicate_case(sample, str(entry["target_case_id"]))
        elif kind == "unsupported_assertion_path":
            mutated = make_assertion_path_unsupported(
                sample,
                str(entry["target_case_id"]),
                str(entry["target_assertion_id"]),
                path=str(entry.get("path") or "$.data[*].id"),
            )
        else:
            raise ValueError(f"unsupported mutation kind: {kind}")
        mutated.sample_id = f"{sample.sample_id}__{mutated.mutation.mutation_id.replace(':', '-') }"
        mutated.variant = "reviewer_mutation"
        mutated.reviewer_output = None
        mutated.telemetry = []
        mutated.metadata = {
            "source": "local-redacted-reviewer-mutation",
            "prompt_version": plan.get("prompt_version") or sample.metadata.get("prompt_version"),
            "mutation_id": mutated.mutation.mutation_id,
        }
        mutations.append(mutated)
    return mutations


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Reviewer 缺陷注入脱敏样本包")
    parser.add_argument("--input", type=Path, required=True, help="基础脱敏 EvalSample JSON")
    parser.add_argument("--plan", type=Path, required=True, help="Reviewer Mutation 计划 YAML")
    parser.add_argument("--output", type=Path, required=True, help="本地忽略目录中的输出 JSON")
    args = parser.parse_args()

    samples, _ = load_samples(args.input, require_redacted=True)
    if len(samples) != 1:
        raise ValueError("Mutation Pack 要求输入文件恰好包含一个基础样本")
    plan = yaml.safe_load(args.plan.read_text(encoding="utf-8")) or {}
    mutations = build_reviewer_mutation_pack(samples[0], plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"samples": [sample.model_dump(mode="json") for sample in mutations]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"status": "prepared", "samples": len(mutations), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
