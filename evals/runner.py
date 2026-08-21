from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from evals.ablation import summarize_ablation
from evals.dataset import enrich_manifest_with_catalog, load_manifest, scaffold_manifest_from_baseline
from evals.fixture_audit import audit_fixture_requirements
from evals.graders.designer import aggregate_designer, grade_designer
from evals.graders.nlu import grade_nlu
from evals.graders.reviewer import aggregate_reviewer_suite, grade_reviewer
from evals.graders.telemetry import aggregate_telemetry, telemetry_from_metadata
from evals.input_audit import audit_input_payload
from evals.models import EvalDatasetManifest, EvalReport, EvalSample


def run_evaluation(
    manifest: EvalDatasetManifest,
    samples: list[EvalSample],
    *,
    source_summary: dict[str, Any] | None = None,
) -> EvalReport:
    operations = {operation.operation_id: operation for operation in manifest.operations}
    sampled_operation_ids = {
        sample.operation_id for sample in samples if sample.operation_id in operations
    }
    missing_operation_ids = sorted(set(operations) - sampled_operation_ids)
    reviewer_controls = {
        sample.operation_id: sample.reviewer_output
        for sample in samples
        if sample.variant == "reviewer_control"
        and sample.mutation is None
        and sample.reviewer_output is not None
    }
    sample_reports: list[dict[str, Any]] = []
    pending_annotation = manifest.annotation_status != "verified"
    for sample in samples:
        operation = operations.get(sample.operation_id)
        if operation is None:
            sample_reports.append(
                {
                    "sample_id": sample.sample_id,
                    "operation_id": sample.operation_id,
                    "variant": sample.variant,
                    "status": "pending_input",
                    "reason": "operation is not present in dataset manifest",
                }
            )
            continue
        nlu = grade_nlu(operation, sample, dataset_status=manifest.annotation_status)
        designer = grade_designer(operation, sample, dataset_status=manifest.annotation_status)
        if operation.annotation_status != "verified":
            pending_annotation = True
        if sample.test_points and not nlu["annotations_complete"]:
            pending_annotation = True
        required_assertion_ids = {
            assertion.assertion_id
            for point in operation.points
            for assertion in point.required_assertions
            if assertion.required
        }
        matched_assertion_ids = {
            item.ground_truth_assertion_id
            for item in sample.annotations.assertion_matches
        }
        reviewed_missing_assertion_ids = set(sample.annotations.reviewed_missing_assertion_ids)
        if required_assertion_ids - matched_assertion_ids - reviewed_missing_assertion_ids:
            pending_annotation = True
        sample_reports.append(
            {
                "sample_id": sample.sample_id,
                "operation_id": sample.operation_id,
                "variant": sample.variant,
                "status": "pending_annotation" if pending_annotation else "ready",
                "nlu": nlu,
                "designer": designer,
                "reviewer": grade_reviewer(sample, reviewer_controls.get(sample.operation_id)),
                "telemetry": aggregate_telemetry(sample.telemetry),
            }
        )
    if pending_annotation:
        status = "pending_annotation"
    elif not samples or missing_operation_ids:
        status = "pending_input"
    else:
        status = "ready"
    report_source_summary = dict(source_summary or {})
    report_source_summary["dataset_coverage"] = {
        "expected_operation_ids": sorted(operations),
        "sampled_operation_ids": sorted(sampled_operation_ids),
        "missing_operation_ids": missing_operation_ids,
        "status": "ready" if not missing_operation_ids else "pending_input",
    }
    component_eval = {
        "nlu": {
            "status": "ready" if any(report.get("nlu") for report in sample_reports) else "pending_input",
            "sample_count": sum(1 for report in sample_reports if report.get("nlu")),
        },
        "designer": aggregate_designer(
            [report.get("designer", {}) for report in sample_reports]
        ),
        "reviewer": {
            "status": aggregate_reviewer_suite(sample_reports).get("status", "pending_input"),
            "sample_count": sum(1 for report in sample_reports if report.get("reviewer")),
        },
        "supplement": {
            "status": "pending_input",
            "reason": "Supplement Recovery Eval is reported separately from initial generation.",
        },
    }
    e2e_eval = {
        "status": "pending_input",
        "reason": "Initial EvalSample input does not contain mutated Draft Cases and Recovery outputs.",
    }
    telemetry_summary = aggregate_telemetry(
        [record for sample in samples for record in sample.telemetry]
    )
    return EvalReport(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        samples=sample_reports,
        reviewer_summary=aggregate_reviewer_suite(sample_reports),
        ablation=summarize_ablation(sample_reports),
        component_eval=component_eval,
        e2e_eval=e2e_eval,
        telemetry_summary=telemetry_summary,
        source_summary=report_source_summary,
    )


def load_samples(
    path: Path | None,
    *,
    require_redacted: bool = False,
) -> tuple[list[EvalSample], dict[str, Any]]:
    if path is None:
        return [], {"status": "no_input"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if require_redacted:
        audit = audit_input_payload(payload)
        if audit["status"] != "ready":
            raise ValueError(
                "evaluation input failed redaction audit: "
                + json.dumps(audit["issues"], ensure_ascii=False)
            )
    if isinstance(payload, list):
        samples = [EvalSample.model_validate(item) for item in payload]
        return _hydrate_sample_telemetry(samples), {"path": str(path)}
    if not isinstance(payload, dict):
        raise ValueError("evaluation input must be a JSON object or list")
    if "samples" in payload:
        samples = [EvalSample.model_validate(item) for item in payload["samples"]]
        return _hydrate_sample_telemetry(samples), {"path": str(path)}
    if "test_points" in payload or "final_cases" in payload or "draft_cases" in payload:
        sample = EvalSample.from_workflow_snapshot(
            payload,
            sample_id=path.stem,
            annotations=None,
        )
        if not sample.operation_id:
            raise ValueError("workflow snapshot must contain operation_id")
        return [sample], {"path": str(path), "format": "workflow_snapshot"}
    if "baseline_definition" in payload and "apis" in payload:
        return [], {
            "path": str(path),
            "format": "metrics_summary_only",
            "status": "pending_input",
            "reason": "metrics summary has no Requirement/Test Point/Case/Assertion snapshots",
            "baseline_size": payload.get("baseline_size"),
        }
    raise ValueError("input does not contain EvalSample or workflow snapshot data")


def _hydrate_sample_telemetry(samples: list[EvalSample]) -> list[EvalSample]:
    """让直接保存的 EvalSample 也能从脱敏 metadata 恢复调用统计。"""

    for sample in samples:
        if not sample.telemetry and sample.metadata:
            sample.telemetry = telemetry_from_metadata(sample.metadata)
    return samples


def write_report(report: EvalReport, output: Path) -> tuple[Path, Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    json_path = output if output.suffix == ".json" else output.with_suffix(".json")
    html_path = json_path.with_suffix(".html")
    payload = report.model_dump(mode="json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(payload), encoding="utf-8")
    return json_path, html_path


def render_html(payload: dict[str, Any]) -> str:
    title = f"LLM Eval Report - {payload['dataset_id']}"
    rows: list[str] = []
    for sample in payload.get("samples", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(sample.get('sample_id', '')))}</td>"
            f"<td>{html.escape(str(sample.get('variant', '')))}</td>"
            f"<td>{html.escape(str(sample.get('status', '')))}</td>"
            f"<td>{html.escape(_metric_text(sample.get('nlu', {}).get('response_test_point_recall')))}</td>"
            f"<td>{html.escape(_metric_text(sample.get('nlu', {}).get('observation_test_point_recall')))}</td>"
            f"<td>{html.escape(_metric_text(sample.get('designer', {}).get('response_test_point_coverage')))}</td>"
            f"<td>{html.escape(_metric_text(sample.get('designer', {}).get('observation_coverage')))}</td>"
            f"<td>{html.escape(_metric_text(sample.get('designer', {}).get('assertion_coverage')))}</td>"
            f"<td>{html.escape(_metric_text(sample.get('reviewer', {}).get('gap_recall')))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="9">暂无可评分样本</td></tr>'
    reviewer_summary = payload.get("reviewer_summary", {})
    designer_summary = payload.get("component_eval", {}).get("designer", {})
    designer_text = (
        "Designer Assertion Coverage："
        f"{_metric_text(designer_summary.get('assertion_coverage'))}；"
        f"{designer_summary.get('matched_required_assertions', 0)}/"
        f"{designer_summary.get('required_assertions', 0)}"
    )
    reviewer_text = (
        "Reviewer Mutation："
        f"Recall {_metric_text(reviewer_summary.get('defect_recall'))}，"
        f"Precision {_metric_text(reviewer_summary.get('gap_precision_micro'))}，"
        f"False Positive Rate {_metric_text(reviewer_summary.get('false_positive_rate_micro'))}"
    )
    escaped_json = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;color:#202124}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.5rem;text-align:left}}pre{{background:#f6f8fa;padding:1rem;overflow:auto}}</style>
</head><body><h1>{html.escape(title)}</h1><p>状态：{html.escape(str(payload['status']))}</p><p>{html.escape(designer_text)}；{html.escape(reviewer_text)}</p>
<table><thead><tr><th>样本</th><th>变体</th><th>状态</th><th>NLU Response Recall</th><th>NLU Observation Recall</th><th>Designer Response Coverage</th><th>Designer Observation Coverage</th><th>Assertion Coverage</th><th>Reviewer Gap Recall</th></tr></thead>
<tbody>{body}</tbody></table><h2>原始 JSON</h2><pre>{escaped_json}</pre></body></html>"""


def _metric_text(metric: Any) -> str:
    if not isinstance(metric, dict):
        return "pending"
    if metric.get("value") is None:
        return str(metric.get("status") or "pending")
    return f"{float(metric['value']):.2%}"


def main() -> int:
    parser = argparse.ArgumentParser(description="运行离线 Multi-Agent 质量评测")
    parser.add_argument("--dataset", type=Path, help="EvalDatasetManifest YAML 路径")
    parser.add_argument("--input", type=Path, help="EvalSample 或 workflow snapshot JSON")
    parser.add_argument("--output", type=Path, default=Path("evals/reports/eval_report"))
    parser.add_argument("--scaffold-from-baseline", type=Path, help="从本地 baseline 指标生成待标注 manifest")
    parser.add_argument("--manifest-output", type=Path, default=Path("evals/datasets/baseline_v1/manifest.yaml"))
    parser.add_argument("--catalog", type=Path, help="用本地需求目录为 baseline manifest 补充候选 Ground Truth")
    parser.add_argument("--fixture-audit", type=Path, help="只读审计 Ground Truth 的脱敏 Fixture 计划")
    parser.add_argument("--fixture-audit-output", type=Path, help="Fixture 审计 JSON 输出路径")
    parser.add_argument("--audit-input", type=Path, help="只读审计 EvalSample 或 workflow snapshot 的脱敏状态")
    parser.add_argument("--require-redacted-input", action="store_true", help="运行评测前强制通过输入脱敏审计")
    args = parser.parse_args()

    if args.scaffold_from_baseline:
        manifest = scaffold_manifest_from_baseline(args.scaffold_from_baseline, args.manifest_output)
        if args.catalog:
            manifest = enrich_manifest_with_catalog(manifest, args.catalog)
            args.manifest_output.write_text(
                yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        print(json.dumps({"status": "scaffolded", "manifest": str(args.manifest_output), "operations": len(manifest.operations)}, ensure_ascii=False))
        return 0
    if args.fixture_audit:
        manifest = load_manifest(args.fixture_audit)
        audit = audit_fixture_requirements(manifest)
        if args.fixture_audit_output:
            args.fixture_audit_output.parent.mkdir(parents=True, exist_ok=True)
            args.fixture_audit_output.write_text(
                json.dumps(audit, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(json.dumps(audit, ensure_ascii=False))
        return 0 if audit["status"] == "ready" else 2
    if args.audit_input:
        payload = json.loads(args.audit_input.read_text(encoding="utf-8"))
        audit = audit_input_payload(payload)
        print(json.dumps(audit, ensure_ascii=False))
        return 0 if audit["status"] == "ready" else 2
    if not args.dataset:
        parser.error("--dataset is required unless --scaffold-from-baseline is used")
    manifest = load_manifest(args.dataset)
    samples, source_summary = load_samples(args.input, require_redacted=args.require_redacted_input)
    report = run_evaluation(manifest, samples, source_summary=source_summary)
    json_path, html_path = write_report(report, args.output)
    print(json.dumps({"status": report.status, "json": str(json_path), "html": str(html_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
