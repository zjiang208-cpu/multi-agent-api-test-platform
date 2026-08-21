from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from evals.input_audit import audit_input_payload
from evals.models import EvalSample, GeneratedCase, GeneratedReviewerOutput
from evals.runner import load_samples


def _reviewer_output(payload: dict) -> GeneratedReviewerOutput:
    return GeneratedReviewerOutput(
        missing_test_point_ids=payload.get("missing_test_point_ids") or [],
        invalid_case_ids=payload.get("invalid_case_ids") or [],
        duplicate_case_ids=payload.get("duplicate_case_ids") or [],
        unsupported_assertion_ids=payload.get("unsupported_assertion_ids") or [],
        semantic_gaps=payload.get("semantic_gaps") or [],
        remaining_gaps=payload.get("remaining_gaps") or [],
    )


def build_ablation_pack(base: EvalSample, snapshot: dict) -> list[EvalSample]:
    if str(snapshot.get("operation_id") or "") != base.operation_id:
        raise ValueError("workflow snapshot and redacted sample operation_id differ")
    draft_payload = (snapshot.get("draft_cases") or {}).get("cases") or []
    final_payload = (snapshot.get("final_cases") or {}).get("cases") or []
    if not draft_payload or not final_payload:
        raise ValueError("workflow snapshot lacks draft or final cases")

    designer = base.model_copy(deep=True)
    designer.sample_id = f"{base.sample_id}__designer"
    designer.variant = "designer"
    designer.cases = [GeneratedCase.model_validate(case) for case in draft_payload]
    designer.reviewer_output = None
    designer.telemetry = [
        record for record in designer.telemetry if record.stage in {"nlu", "designer"}
    ]
    designer.metadata = {
        "source": "local-redacted-ablation",
        "variant": "designer",
        "prompt_version": base.metadata.get("prompt_version"),
    }

    reviewer = base.model_copy(deep=True)
    reviewer.sample_id = f"{base.sample_id}__reviewer"
    reviewer.variant = "reviewer"
    reviewer.cases = [GeneratedCase.model_validate(case) for case in final_payload]
    reviewer.reviewer_output = _reviewer_output(snapshot.get("reviewer_output") or {})
    reviewer.metadata = {
        "source": "local-redacted-ablation",
        "variant": "reviewer",
        "prompt_version": base.metadata.get("prompt_version"),
        "case_count_delta": len(final_payload) - len(draft_payload),
        "assertion_count_delta": sum(len(case.get("assertions") or []) for case in final_payload)
        - sum(len(case.get("assertions") or []) for case in draft_payload),
    }
    return [designer, reviewer]


def main() -> int:
    parser = argparse.ArgumentParser(description="从同一 Workflow 快照生成 Designer/Reviewer Ablation 包")
    parser.add_argument("--input", type=Path, required=True, help="基础脱敏 EvalSample")
    parser.add_argument("--snapshot", type=Path, required=True, help="本地私有 Workflow 快照")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    samples, _ = load_samples(args.input, require_redacted=True)
    if len(samples) != 1:
        raise ValueError("ablation pack requires exactly one base EvalSample")
    snapshot = yaml.safe_load(args.snapshot.read_text(encoding="utf-8")) or {}
    variants = build_ablation_pack(samples[0], snapshot)
    payload = {"samples": [sample.model_dump(mode="json") for sample in variants]}
    audit = audit_input_payload(payload)
    if audit["status"] != "ready":
        raise ValueError("ablation pack failed redaction audit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": "prepared", "samples": len(variants), "output": str(args.output)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
