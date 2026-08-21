from __future__ import annotations

from collections import defaultdict
from typing import Any


ABLATION_METRICS = (
    "test_point_coverage",
    "response_test_point_coverage",
    "observation_coverage",
    "assertion_coverage",
    "executable_case_rate",
    "duplicate_rate",
)
DEFAULT_VARIANT_ORDER = ("designer", "reviewer", "supplement", "rules", "full")


def summarize_ablation(sample_reports: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in sample_reports:
        grouped[str(report.get("variant") or "full")].append(report)
    summaries: dict[str, Any] = {}
    for variant, reports in grouped.items():
        metrics: dict[str, Any] = {}
        for metric_name in ABLATION_METRICS:
            values = [
                report.get("designer", {}).get(metric_name, {}).get("value")
                for report in reports
                if report.get("designer", {}).get(metric_name, {}).get("status") == "ready"
            ]
            metrics[metric_name] = {
                "value": round(sum(values) / len(values), 4) if values else None,
                "samples": len(values),
                "status": "ready" if values else "pending_input",
            }
        diagnostic_counts: dict[str, int] = defaultdict(int)
        diagnostic_samples = 0
        for report in reports:
            finding_counts = report.get("reviewer", {}).get("finding_counts")
            if not isinstance(finding_counts, dict):
                continue
            diagnostic_samples += 1
            for field, count in finding_counts.items():
                diagnostic_counts[str(field)] += int(count)
        summaries[variant] = {
            "sample_count": len(reports),
            "metrics": metrics,
            "reviewer_diagnostics": {
                "status": "ready" if diagnostic_samples else "pending_input",
                "samples": diagnostic_samples,
                "finding_count_total": sum(diagnostic_counts.values()),
                "finding_counts": dict(sorted(diagnostic_counts.items())),
            },
        }

    baseline_variant = next(
        (variant for variant in DEFAULT_VARIANT_ORDER if variant in summaries),
        next(iter(summaries), None),
    )
    baseline = summaries.get(baseline_variant, {}).get("metrics", {}) if baseline_variant else {}
    deltas: dict[str, Any] = {}
    for variant, summary in summaries.items():
        deltas[variant] = {}
        for metric_name in ABLATION_METRICS:
            current = summary["metrics"][metric_name]["value"]
            reference = baseline.get(metric_name, {}).get("value")
            deltas[variant][metric_name] = (
                round(current - reference, 4)
                if current is not None and reference is not None
                else None
            )
    return {
        "baseline_variant": baseline_variant,
        "variants": summaries,
        "deltas_vs_baseline": deltas,
    }
