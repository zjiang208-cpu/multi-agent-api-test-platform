from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from evals.input_audit import audit_input_payload
from evals.runner import load_samples


def main() -> int:
    parser = argparse.ArgumentParser(description="按 Mutation 计划组装 Reviewer 对照评测包")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    plan = yaml.safe_load(args.plan.read_text(encoding="utf-8")) or {}
    expected_ids = [str(item["mutation_id"]) for item in plan.get("mutations", [])]
    controls = []
    mutation_samples = {}
    for path in args.input:
        samples, _ = load_samples(path, require_redacted=True)
        for sample in samples:
            if sample.variant == "reviewer_control" and sample.reviewer_output is not None:
                controls = [sample]
            elif sample.mutation is not None and sample.reviewer_output is not None:
                mutation_samples[sample.mutation.mutation_id] = sample
    missing = [mutation_id for mutation_id in expected_ids if mutation_id not in mutation_samples]
    if len(controls) != 1 or missing:
        raise ValueError(
            f"suite inputs incomplete: control={len(controls)}, missing_mutations={missing}"
        )
    selected = [*controls, *(mutation_samples[mutation_id] for mutation_id in expected_ids)]
    payload = {"samples": [sample.model_dump(mode="json") for sample in selected]}
    audit = audit_input_payload(payload)
    if audit["status"] != "ready":
        raise ValueError("assembled reviewer suite failed redaction audit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": "assembled", "samples": len(selected), "output": str(args.output)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
