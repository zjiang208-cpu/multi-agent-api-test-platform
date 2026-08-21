from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import AppSettings
from app.projects.service import ProjectService
from app.projects.store import ProjectStore
from app.requirements.operation_store import OperationStore
from app.workflow.models import WorkflowRunSnapshot
from app.workflow.prompts import WORKFLOW_PROMPT_VERSION
from app.workflow.service import WorkflowService
from evals.input_audit import audit_input_payload
from evals.models import EvalSample, TelemetryRecord
from evals.mutations.build_pack import build_reviewer_mutation_pack
from evals.mutations.runtime import mutate_runtime_cases, reviewer_result
from evals.runner import load_samples


def load_workflow_snapshot(path: Path) -> WorkflowRunSnapshot:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return WorkflowRunSnapshot.model_validate(payload)


def reviewer_telemetry(agent) -> list[TelemetryRecord]:
    return [
        TelemetryRecord(
            stage=metric.stage,
            attempt=metric.attempt,
            duration_ms=metric.duration_ms,
            status=metric.status,
            mode=metric.mode,
            error_category=metric.error_category,
            prompt_tokens=metric.prompt_tokens,
            completion_tokens=metric.completion_tokens,
            reasoning_tokens=metric.reasoning_tokens,
        )
        for metric in agent.last_metrics
    ]


def validate_inputs(
    snapshot: WorkflowRunSnapshot,
    base_sample: EvalSample,
    plan: dict[str, Any],
) -> list[EvalSample]:
    if not all(
        [snapshot.requirement, snapshot.evidence, snapshot.test_points, snapshot.draft_cases]
    ):
        raise ValueError("workflow snapshot lacks Reviewer input fields")
    if snapshot.operation_id != base_sample.operation_id:
        raise ValueError("workflow snapshot and redacted sample operation_id differ")
    plan_version = str(plan.get("prompt_version") or "")
    if plan_version and plan_version != WORKFLOW_PROMPT_VERSION:
        raise ValueError(
            f"mutation plan prompt version is stale: {plan_version} != {WORKFLOW_PROMPT_VERSION}"
        )
    snapshot_version = str(snapshot.metadata.get("prompt_version") or "")
    if snapshot_version and snapshot_version != WORKFLOW_PROMPT_VERSION:
        raise ValueError(
            f"workflow snapshot prompt version is stale: {snapshot_version} != {WORKFLOW_PROMPT_VERSION}"
        )

    prepared = build_reviewer_mutation_pack(base_sample, plan)
    entries = list(plan.get("mutations") or [])
    if len(prepared) != len(entries):
        raise ValueError("mutation plan and prepared sample count differ")
    for sample, entry in zip(prepared, entries, strict=True):
        mutate_runtime_cases(snapshot.draft_cases, entry)
        if sample.mutation is None or sample.mutation.mutation_id != str(entry["mutation_id"]):
            raise ValueError("mutation plan and generated mutation_id differ")
    return prepared


def run_reviewer_mutations(
    *,
    snapshot: WorkflowRunSnapshot,
    base_sample: EvalSample,
    plan: dict[str, Any],
    data_dir: Path,
    mutation_id: str | None = None,
) -> list[EvalSample]:
    prepared = validate_inputs(snapshot, base_sample, plan)
    project_service = ProjectService(ProjectStore(data_dir))
    project = project_service.get(snapshot.project_id)
    operation = OperationStore(data_dir, snapshot.project_id).get(snapshot.operation_id)
    if operation is None:
        raise ValueError(f"operation not found in local project data: {snapshot.operation_id}")

    settings = AppSettings(data_dir=data_dir)
    graph = WorkflowService(project_service, data_dir, settings)._workflow_for(project)
    entries = list(plan.get("mutations") or [])
    state = {
        "operation": operation,
        "requirement": snapshot.requirement,
        "test_points": snapshot.test_points,
        "evidence": snapshot.evidence,
    }
    evidence = graph._downstream_evidence(state)

    selected = [
        (sample, entry)
        for sample, entry in zip(prepared, entries, strict=True)
        if mutation_id is None or str(entry.get("mutation_id")) == mutation_id
    ]
    if mutation_id is not None and not selected:
        raise ValueError(f"mutation_id not found in plan: {mutation_id}")
    for sample, entry in selected:
        draft_cases = mutate_runtime_cases(snapshot.draft_cases, entry)
        try:
            output = graph.reviewer_agent.invoke(
                {
                    "review_stage": "initial",
                    "operation": operation,
                    "requirement": snapshot.requirement,
                    "test_points": snapshot.test_points,
                    "draft_cases": draft_cases,
                    "evidence": evidence,
                }
            )
        except Exception:
            sample.metadata["reviewer_run_status"] = "failed"
            sample.telemetry = reviewer_telemetry(graph.reviewer_agent)
            continue
        sample.reviewer_output = reviewer_result(output)
        sample.telemetry = reviewer_telemetry(graph.reviewer_agent)
        sample.metadata["reviewer_run_status"] = "completed"
    return [sample for sample, _ in selected]


def run_reviewer_control(
    *,
    snapshot: WorkflowRunSnapshot,
    base_sample: EvalSample,
    plan: dict[str, Any],
    data_dir: Path,
) -> EvalSample:
    validate_inputs(snapshot, base_sample, plan)
    project_service = ProjectService(ProjectStore(data_dir))
    project = project_service.get(snapshot.project_id)
    operation = OperationStore(data_dir, snapshot.project_id).get(snapshot.operation_id)
    if operation is None:
        raise ValueError(f"operation not found in local project data: {snapshot.operation_id}")
    settings = AppSettings(data_dir=data_dir)
    graph = WorkflowService(project_service, data_dir, settings)._workflow_for(project)
    state = {
        "operation": operation,
        "requirement": snapshot.requirement,
        "test_points": snapshot.test_points,
        "evidence": snapshot.evidence,
    }
    control = base_sample.model_copy(deep=True)
    control.sample_id = f"{base_sample.sample_id}__reviewer-control"
    control.variant = "reviewer_control"
    control.mutation = None
    control.reviewer_output = None
    control.telemetry = []
    control.metadata = {
        "source": "local-redacted-reviewer-control",
        "prompt_version": WORKFLOW_PROMPT_VERSION,
        "reviewer_run_status": "pending",
    }
    try:
        output = graph.reviewer_agent.invoke(
            {
                "review_stage": "initial",
                "operation": operation,
                "requirement": snapshot.requirement,
                "test_points": snapshot.test_points,
                "draft_cases": snapshot.draft_cases,
                "evidence": graph._downstream_evidence(state),
            }
        )
    except Exception:
        control.metadata["reviewer_run_status"] = "failed"
        control.telemetry = reviewer_telemetry(graph.reviewer_agent)
        return control
    control.reviewer_output = reviewer_result(output)
    control.telemetry = reviewer_telemetry(graph.reviewer_agent)
    control.metadata["reviewer_run_status"] = "completed"
    return control


def write_redacted_results(path: Path, samples: list[EvalSample]) -> None:
    payload = {"samples": [sample.model_dump(mode="json") for sample in samples]}
    audit = audit_input_payload(payload)
    if audit["status"] != "ready":
        issue_types = sorted({issue["type"] for issue in audit["issues"]})
        raise ValueError(f"reviewer result failed redaction audit: {issue_types}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="调用生产 Reviewer 执行本地缺陷注入评测")
    parser.add_argument("--snapshot", type=Path, required=True, help="本地私有 Workflow 快照 YAML")
    parser.add_argument("--base-sample", type=Path, required=True, help="基础脱敏 EvalSample JSON")
    parser.add_argument("--plan", type=Path, required=True, help="Reviewer Mutation 计划 YAML")
    parser.add_argument("--data-dir", type=Path, default=BACKEND_ROOT / ".data")
    parser.add_argument("--output", type=Path, help="本地忽略目录中的脱敏结果 JSON")
    parser.add_argument("--dry-run", action="store_true", help="只验证输入和变异，不调用模型")
    parser.add_argument("--control-only", action="store_true", help="只运行未变异 Reviewer 对照组")
    parser.add_argument("--merge-with", type=Path, help="把已有 Mutation 结果合并到对照组输出")
    parser.add_argument("--mutation-id", help="只运行计划中的一个 Mutation")
    args = parser.parse_args()

    snapshot = load_workflow_snapshot(args.snapshot)
    samples, _ = load_samples(args.base_sample, require_redacted=True)
    if len(samples) != 1:
        raise ValueError("Reviewer Runner 要求基础文件恰好包含一个样本")
    plan = yaml.safe_load(args.plan.read_text(encoding="utf-8")) or {}
    if args.dry_run:
        prepared = validate_inputs(snapshot, samples[0], plan)
        print(
            json.dumps(
                {
                    "status": "validated",
                    "samples": len(prepared),
                    "prompt_version": WORKFLOW_PROMPT_VERSION,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.output is None:
        raise ValueError("非 dry-run 模式必须提供 --output")

    if args.control_only:
        control = run_reviewer_control(
            snapshot=snapshot,
            base_sample=samples[0],
            plan=plan,
            data_dir=args.data_dir.expanduser().resolve(),
        )
        results = [control]
        if args.merge_with is not None:
            existing, _ = load_samples(args.merge_with, require_redacted=True)
            results.extend(existing)
        write_redacted_results(args.output, results)
        completed = int(control.reviewer_output is not None)
        print(
            json.dumps(
                {
                    "status": "completed" if completed else "partial",
                    "control_completed": completed,
                    "samples": len(results),
                    "output": str(args.output),
                },
                ensure_ascii=False,
            )
        )
        return 0 if completed else 1

    results = run_reviewer_mutations(
        snapshot=snapshot,
        base_sample=samples[0],
        plan=plan,
        data_dir=args.data_dir.expanduser().resolve(),
        mutation_id=args.mutation_id,
    )
    write_redacted_results(args.output, results)
    completed = sum(sample.reviewer_output is not None for sample in results)
    print(
        json.dumps(
            {
                "status": "completed" if completed == len(results) else "partial",
                "samples": len(results),
                "completed": completed,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if completed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
