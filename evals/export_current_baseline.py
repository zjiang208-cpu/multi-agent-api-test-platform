from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from evals.generate_baseline_snapshots import _safe_metadata
from evals.input_audit import audit_input_payload
from evals.models import EvalSample


DEFAULT_PROJECT_ID = "project-3dc9250d242f4e459d39b996edd384a1"
OPERATION_ALIASES = {"get-shop-id-2d82e44a": "get-shop-id"}


def _get_json(base_url: str, path: str) -> Any:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=30) as response:
        return json.load(response)


def export_current_baseline(
    *,
    base_url: str,
    project_id: str,
    output_root: Path,
) -> None:
    api_root = f"{base_url.rstrip('/')}/api/projects/{project_id}"
    queues = _get_json(api_root, "/processing-queues")
    if len(queues) != 10:
        raise ValueError(f"基线队列数量应为 10，实际为 {len(queues)}")
    incomplete = [
        (queue["run_id"], queue["status"])
        for queue in queues
        if queue.get("status") != "READY_FOR_EXECUTION"
    ]
    if incomplete:
        raise ValueError(f"仍有未完成队列：{incomplete}")

    sample_dir = output_root / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    samples: list[EvalSample] = []
    summary_entries: list[dict[str, Any]] = []
    for queue in queues:
        for item in queue.get("items", []):
            workflow_id = item.get("workflow_id")
            if not workflow_id:
                raise ValueError(f"队列缺少 workflow_id：{queue.get('run_id')}")
            snapshot = _get_json(api_root, f"/workflows/{workflow_id}")
            source_operation_id = str(snapshot.get("operation_id") or "")
            operation_id = OPERATION_ALIASES.get(source_operation_id, source_operation_id)
            sample = EvalSample.from_workflow_snapshot(
                snapshot,
                sample_id=f"baseline-v1-{operation_id}-current-20260821",
                variant="current-prompt",
            )
            sample.operation_id = operation_id
            sample.metadata = _safe_metadata(snapshot.get("metadata") or {})
            payload = {"samples": [sample.model_dump(mode="json", exclude_none=True)]}
            audit = audit_input_payload(payload)
            if audit["status"] != "ready":
                raise ValueError(
                    f"{operation_id} 脱敏审计未通过："
                    + json.dumps(audit["issues"], ensure_ascii=False)
                )
            sample_path = sample_dir / f"{operation_id}-current-redacted.json"
            sample_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            samples.append(sample)
            summary_entries.append(
                {
                    "operation_id": operation_id,
                    "source_operation_id": source_operation_id,
                    "queue_id": queue["run_id"],
                    "workflow_id": workflow_id,
                    "status": snapshot.get("status"),
                    "test_point_count": len(sample.test_points),
                    "case_count": len(sample.cases),
                    "assertion_count": sum(len(case.assertions) for case in sample.cases),
                    "prompt_version": snapshot.get("metadata", {}).get("prompt_version"),
                    "sample": str(sample_path),
                }
            )

    samples.sort(key=lambda sample: sample.operation_id)
    all_payload = {
        "samples": [sample.model_dump(mode="json", exclude_none=True) for sample in samples]
    }
    (output_root / "all-current-redacted.json").write_text(
        json.dumps(all_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "dataset_id": "baseline_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "isolation": "本地后端已完成工作流的脱敏导出；不含密钥和业务原始数据。",
        "operations": sorted(summary_entries, key=lambda item: item["operation_id"]),
    }
    (output_root / "generation-summary.yaml").write_text(
        yaml.safe_dump(summary, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="导出本地后端已完成的 10 个基线工作流样本")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("evals/reports/baseline_v1/generated/current-20260821"),
    )
    args = parser.parse_args()
    export_current_baseline(
        base_url=args.base_url,
        project_id=args.project_id,
        output_root=args.output_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
