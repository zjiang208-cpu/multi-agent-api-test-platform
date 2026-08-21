from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from evals.dataset import load_manifest
from evals.graders.recovery import aggregate_recovery, grade_recovery
from evals.graders.telemetry import aggregate_telemetry
from evals.input_audit import audit_input_payload
from evals.recovery.models import RecoveryEvalSample


def _metric_text(metric: Any) -> str:
    if not isinstance(metric, dict):
        return "pending"
    value = metric.get("value")
    return "pending" if value is None else f"{float(value):.2%}"


def render_html(payload: dict[str, Any]) -> str:
    rows = []
    for sample in payload.get("samples", []):
        recovery = sample.get("recovery", {})
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(sample.get('operation_id', '')))}</td>"
            f"<td>{html.escape(str(sample.get('variant', '')))}</td>"
            f"<td>{html.escape(_metric_text(recovery.get('detection_rate')))}</td>"
            f"<td>{html.escape(_metric_text(recovery.get('coverage_recovery')))}</td>"
            f"<td>{html.escape(str(recovery.get('final_validator_passed', 'pending')))}</td>"
            "</tr>"
        )
    summary = payload.get("recovery_summary", {})
    body = "".join(rows) or "<tr><td colspan='5'>暂无可评分样本</td></tr>"
    raw = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><title>Workflow Recovery Eval</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;color:#202124}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.5rem;text-align:left}}pre{{background:#f6f8fa;padding:1rem;overflow:auto}}</style>
</head><body><h1>Multi-Agent Workflow Recovery Eval</h1>
<p>状态：{html.escape(str(payload.get('status')))}</p>
<p>Detection：{_metric_text(summary.get('detection_rate'))}；Recovery：{_metric_text(summary.get('recovery_rate'))}；Repair Success：{_metric_text(summary.get('repair_success_rate'))}</p>
<table><thead><tr><th>接口</th><th>变体</th><th>Detection Rate</th><th>Coverage Recovery</th><th>Validator</th></tr></thead><tbody>{body}</tbody></table>
<h2>结构化 JSON</h2><pre>{raw}</pre></body></html>"""


def build_report(dataset_path: Path, input_path: Path) -> dict[str, Any]:
    manifest = load_manifest(dataset_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    audit = audit_input_payload(payload)
    if audit["status"] != "ready":
        raise ValueError("recovery suite failed redaction audit")
    samples = [RecoveryEvalSample.model_validate(item) for item in payload.get("samples", [])]
    expected = {operation.operation_id for operation in manifest.operations}
    observed = {sample.operation_id for sample in samples}
    missing = sorted(expected - observed)
    reports = [
        {
            "sample_id": sample.sample_id,
            "operation_id": sample.operation_id,
            "variant": sample.variant,
            "status": "ready",
            "recovery": grade_recovery(sample),
            "telemetry": aggregate_telemetry(sample.telemetry),
        }
        for sample in samples
    ]
    telemetry = aggregate_telemetry(
        [record for sample in samples for record in sample.telemetry]
    )
    summary = aggregate_recovery(samples)
    return {
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if samples and not missing else "pending_input",
        "component_eval": {
            "reviewer": {
                "status": summary["status"],
                "detection_rate": summary["detection_rate"],
            },
            "supplement": {
                "status": summary["status"],
                "target_recall": summary["supplement_target_recall"],
            },
        },
        "e2e_eval": {
            "status": summary["status"],
            "recovery_rate": summary["recovery_rate"],
            "final_validator_pass_rate": summary["final_validator_pass_rate"],
            "repair_success_rate": summary["repair_success_rate"],
        },
        "recovery_summary": summary,
        "telemetry": telemetry,
        "samples": reports,
        "source_summary": {
            "input": str(input_path),
            "expected_operation_ids": sorted(expected),
            "observed_operation_ids": sorted(observed),
            "missing_operation_ids": missing,
            "dataset_coverage_status": "ready" if not missing else "pending_input",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Workflow Recovery Eval 报告")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_report(args.dataset, args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output if args.output.suffix == ".json" else args.output.with_suffix(".json")
    html_path = json_path.with_suffix(".html")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "json": str(json_path), "html": str(html_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
