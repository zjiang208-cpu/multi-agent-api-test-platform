from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


_METRICS = {
    "coverage_recovery_rate": "recovery_rate",
    "defect_recovery_rate": "defect_recovery_rate",
    "detection_rate": "detection_rate",
    "supplement_target_recall": "supplement_target_recall",
    "repair_success_rate": "repair_success_rate",
    "final_validator_pass_rate": "final_validator_pass_rate",
    "clean_control_alarm_rate": "clean_control_alarm_rate",
}


def _load_ready_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "ready":
        raise ValueError(f"experiment input is not ready: {path}")
    source_summary = payload.get("source_summary") or {}
    if source_summary.get("dataset_coverage_status") != "ready":
        raise ValueError(f"experiment input has incomplete dataset coverage: {path}")
    summary = payload.get("recovery_summary") or {}
    if summary.get("status") != "ready":
        raise ValueError(f"experiment input has no ready recovery summary: {path}")
    return payload


def _metric_record(summary: dict[str, Any], metric_name: str, source_name: str) -> dict[str, Any]:
    metric = summary.get(source_name)
    if not isinstance(metric, dict) or metric.get("value") is None:
        raise ValueError(f"metric {metric_name} is pending in report")
    return {
        "value": float(metric["value"]),
        "numerator": int(metric.get("numerator", 0)),
        "denominator": int(metric.get("denominator", 0)),
    }


def _dataset_identity(payload: dict[str, Any]) -> dict[str, Any]:
    source_summary = payload.get("source_summary") or {}
    return {
        "dataset_id": payload.get("dataset_id"),
        "dataset_version": payload.get("dataset_version"),
        "expected_operation_ids": source_summary.get("expected_operation_ids", []),
    }


def _same_dataset(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left["dataset_id"] == right["dataset_id"]
        and left["dataset_version"] == right["dataset_version"]
        and left["expected_operation_ids"] == right["expected_operation_ids"]
    )


def build_experiment_report(
    report_paths: list[Path],
    *,
    threshold: float = 0.90,
) -> dict[str, Any]:
    if len(report_paths) < 2:
        raise ValueError("an experiment summary requires at least two ready runs")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")

    payloads = [_load_ready_report(path) for path in report_paths]
    identities = [_dataset_identity(payload) for payload in payloads]
    if any(not _same_dataset(identities[0], identity) for identity in identities[1:]):
        raise ValueError("experiment runs must use the same dataset identity and operation set")

    runs: list[dict[str, Any]] = []
    for path, payload in zip(report_paths, payloads):
        summary = payload["recovery_summary"]
        metrics = {
            output_name: _metric_record(summary, output_name, source_name)
            for output_name, source_name in _METRICS.items()
        }
        runs.append(
            {
                "run_id": path.stem,
                "report": str(path),
                "generated_at": payload.get("generated_at"),
                "metrics": metrics,
            }
        )

    metrics_summary: dict[str, Any] = {}
    for metric_name in _METRICS:
        values = [run["metrics"][metric_name]["value"] for run in runs]
        numerators = [run["metrics"][metric_name]["numerator"] for run in runs]
        denominators = [run["metrics"][metric_name]["denominator"] for run in runs]
        pooled_denominator = sum(denominators)
        pooled_numerator = sum(numerators)
        metrics_summary[metric_name] = {
            "values": values,
            "mean": statistics.fmean(values),
            "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "pooled": {
                "numerator": pooled_numerator,
                "denominator": pooled_denominator,
                "value": (
                    pooled_numerator / pooled_denominator
                    if pooled_denominator
                    else None
                ),
            },
        }

    threshold_values = [run["metrics"]["coverage_recovery_rate"]["value"] for run in runs]
    return {
        "status": "ready",
        "experiment_type": "repeated_recovery_eval",
        "dataset": identities[0],
        "run_count": len(runs),
        "threshold_metric": "coverage_recovery_rate",
        "threshold": threshold,
        "all_runs_meet_threshold": all(value >= threshold for value in threshold_values),
        "mean_meets_threshold": statistics.fmean(threshold_values) >= threshold,
        "metrics": metrics_summary,
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总多轮 Recovery Eval 实验结果")
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--threshold", type=float, default=0.90)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_experiment_report(args.report, threshold=args.threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": payload["status"],
        "run_count": payload["run_count"],
        "all_runs_meet_threshold": payload["all_runs_meet_threshold"],
        "mean_meets_threshold": payload["mean_meets_threshold"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
