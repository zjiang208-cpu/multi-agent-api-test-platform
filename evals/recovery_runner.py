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
from evals.models import EvalSample, GeneratedCase
from evals.mutations.runtime import reviewer_result
from evals.reviewer_runner import reviewer_telemetry
from evals.recovery.models import RecoveryEvalSample, RecoveryMutationSpec
from evals.environment import hydrate_environment_from_project_config
from evals.recovery.runtime import mutate_recovery_cases, reviewer_summary
from evals.runner import load_samples


def load_workflow_snapshot(path: Path) -> WorkflowRunSnapshot:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return WorkflowRunSnapshot.model_validate(payload)


def _generated_cases(cases) -> list[GeneratedCase]:
    return [GeneratedCase.model_validate(case.model_dump(mode="json")) for case in cases]


def _validate_inputs(
    snapshot: WorkflowRunSnapshot,
    base_sample: EvalSample,
    plan: dict[str, Any],
) -> RecoveryMutationSpec:
    if not all([snapshot.requirement, snapshot.evidence, snapshot.test_points, snapshot.draft_cases]):
        raise ValueError("workflow snapshot lacks Recovery input fields")
    if snapshot.operation_id != base_sample.operation_id:
        raise ValueError("workflow snapshot and redacted sample operation_id differ")
    plan_version = str(plan.get("prompt_version") or "")
    if plan_version and plan_version != WORKFLOW_PROMPT_VERSION:
        raise ValueError(
            f"recovery plan prompt version is stale: {plan_version} != {WORKFLOW_PROMPT_VERSION}"
        )
    mutation = RecoveryMutationSpec.model_validate(plan.get("mutation") or {})
    target = next(
        (case for case in snapshot.draft_cases.cases if case.case_id == mutation.target_case_id),
        None,
    )
    if target is None:
        raise ValueError(f"recovery target case is not in workflow snapshot: {mutation.target_case_id}")
    if set(mutation.target_test_point_ids) != set(target.test_point_ids):
        raise ValueError("recovery target points do not match the selected draft case")
    return mutation


def _initial_state(snapshot: WorkflowRunSnapshot, draft_cases) -> dict[str, Any]:
    return {
        "workflow_id": f"{snapshot.workflow_id}-recovery",
        "project_id": snapshot.project_id,
        "operation_id": snapshot.operation_id,
        "input_document_id": snapshot.source_document_id,
        "operation": None,
        "requirement": snapshot.requirement,
        "test_points": snapshot.test_points,
        "evidence": snapshot.evidence,
        "draft_cases": draft_cases,
        "designer_notes": [],
        "supplemental_cases": [],
        "supplement_notes": [],
        "events": [],
        "status": "REVIEWING",
    }


def _run_production_recovery(
    *,
    snapshot: WorkflowRunSnapshot,
    data_dir: Path,
    draft_cases,
) -> tuple[dict[str, Any], list[Any], Any | None]:
    project_service = ProjectService(ProjectStore(data_dir))
    operation = OperationStore(data_dir, snapshot.project_id).get(snapshot.operation_id)
    if operation is None:
        raise ValueError(f"operation not found in local project data: {snapshot.operation_id}")
    project = project_service.get(snapshot.project_id)
    settings = AppSettings(data_dir=data_dir)
    graph = WorkflowService(project_service, data_dir, settings)._workflow_for(project)
    state = _initial_state(snapshot, draft_cases)
    state["operation"] = operation

    reviewer_delta = graph._reviewer_agent_node(state)
    state = {**state, **reviewer_delta}
    initial_review = state.get("reviewer_output")
    initial_review_summary = (
        reviewer_summary(initial_review) if initial_review is not None else {}
    )
    if state["reviewer_output"].suggested_case_specs:
        supplement_delta = graph._supplement_designer_agent_node(state)
        state = {**state, **supplement_delta}
        validator_delta = graph._local_final_validator_node(state)
        state = {**state, **validator_delta}
    final_delta = graph._final_case_assembler(state)
    state = {**state, **final_delta}
    telemetry = [
        *reviewer_telemetry(graph.reviewer_agent),
        *reviewer_telemetry(graph.designer_agent),
    ]
    return state, telemetry, initial_review


def run_recovery_sample(
    *,
    snapshot: WorkflowRunSnapshot,
    base_sample: EvalSample,
    plan: dict[str, Any],
    data_dir: Path,
    mutation: RecoveryMutationSpec | None,
) -> RecoveryEvalSample:
    if mutation is not None:
        _validate_inputs(snapshot, base_sample, plan)
        draft_cases = mutate_recovery_cases(snapshot.draft_cases, mutation)
        variant = "recovery_mutation"
        sample_id = f"{base_sample.sample_id}__{mutation.mutation_id.replace(':', '-')}"
    else:
        if not all([snapshot.requirement, snapshot.evidence, snapshot.test_points, snapshot.draft_cases]):
            raise ValueError("workflow snapshot lacks Recovery control input fields")
        draft_cases = snapshot.draft_cases.model_copy(deep=True)
        variant = "recovery_control"
        sample_id = f"{base_sample.sample_id}__recovery-control"

    state, telemetry, initial_review = _run_production_recovery(
        snapshot=snapshot,
        data_dir=data_dir,
        draft_cases=draft_cases,
    )
    review = state.get("reviewer_output")
    initial_review_summary = (
        reviewer_summary(initial_review) if initial_review is not None else {}
    )
    review_summary = reviewer_summary(review) if review is not None else {}
    final_cases = state.get("final_cases")
    return RecoveryEvalSample(
        sample_id=sample_id,
        operation_id=base_sample.operation_id,
        variant=variant,
        original_cases=_generated_cases(snapshot.draft_cases.cases),
        mutated_cases=_generated_cases(draft_cases.cases),
        reviewer_initial_output=(
            reviewer_result(initial_review) if initial_review is not None else None
        ),
        reviewer_initial_suggested_test_point_ids=initial_review_summary.get(
            "suggested_test_point_ids", []
        ),
        reviewer_output=reviewer_result(review) if review is not None else None,
        reviewer_suggested_test_point_ids=initial_review_summary.get(
            "suggested_test_point_ids", []
        ),
        supplemental_cases=_generated_cases(state.get("supplemental_cases", [])),
        final_cases=_generated_cases(final_cases.cases) if final_cases else [],
        final_status=final_cases.status if final_cases else None,
        final_added_case_ids=list(final_cases.added_case_ids) if final_cases else [],
        final_remaining_gaps=list(final_cases.remaining_gaps) if final_cases else [],
        final_assembly_errors=list(final_cases.assembly_errors) if final_cases else [],
        mutation=mutation,
        telemetry=telemetry,
        metadata={
            "source": "local-redacted-production-recovery",
            "prompt_version": WORKFLOW_PROMPT_VERSION,
            "reviewer_run_status": "completed" if review is not None else "failed",
            "reviewer_suggested_case_count": initial_review_summary.get(
                "suggested_case_count", 0
            ),
            "final_status": final_cases.status if final_cases else "missing",
        },
    )


def write_redacted_results(path: Path, samples: list[RecoveryEvalSample]) -> None:
    payload = {"samples": [sample.model_dump(mode="json") for sample in samples]}
    audit = audit_input_payload(payload)
    if audit["status"] != "ready":
        issue_types = sorted({issue["type"] for issue in audit["issues"]})
        raise ValueError(f"recovery result failed redaction audit: {issue_types}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="运行真实生产 Workflow 的 Supplement Recovery Eval")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--base-sample", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=BACKEND_ROOT / ".data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    loaded_environment_refs = hydrate_environment_from_project_config([args.data_dir])
    if loaded_environment_refs:
        print(
            json.dumps(
                {"loaded_user_environment_refs": loaded_environment_refs},
                ensure_ascii=False,
            )
        )

    snapshot = load_workflow_snapshot(args.snapshot)
    samples, _ = load_samples(args.base_sample, require_redacted=True)
    if len(samples) != 1:
        raise ValueError("Recovery Runner 要求基础文件恰好包含一个样本")
    plan = yaml.safe_load(args.plan.read_text(encoding="utf-8")) or {}
    mutation = _validate_inputs(snapshot, samples[0], plan)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "validated",
                    "operation_id": snapshot.operation_id,
                    "mutation_id": mutation.mutation_id,
                    "target_test_point_ids": mutation.target_test_point_ids,
                },
                ensure_ascii=False,
            )
        )
        return 0
    result = run_recovery_sample(
        snapshot=snapshot,
        base_sample=samples[0],
        plan=plan,
        data_dir=args.data_dir.expanduser().resolve(),
        mutation=mutation,
    )
    write_redacted_results(args.output, [result])
    completed = result.metadata.get("reviewer_run_status") == "completed"
    print(json.dumps({"status": "completed" if completed else "partial", "output": str(args.output)}, ensure_ascii=False))
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
