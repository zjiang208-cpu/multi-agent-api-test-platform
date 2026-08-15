from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.queue import ApiProcessingItem, ApiProcessingQueue
from app.requirements.yaml_store import ArtifactError
from app.workflow.models import FinalCaseSet
from app.workflow.queue_store import QueueStore
from app.workflow.store import WorkflowStore


@dataclass(frozen=True)
class CompletedProjectCases:
    queue: ApiProcessingQueue
    item: ApiProcessingItem
    final_cases: FinalCaseSet


def completed_project_cases(
    data_dir: Path,
    project_id: str,
    *,
    runtime_session_id: str | None = None,
) -> list[CompletedProjectCases]:
    """Return the newest frozen Final Cases for each completed API in a project."""

    workflow_store = WorkflowStore(data_dir, project_id)
    completed: list[CompletedProjectCases] = []
    seen_operation_ids: set[str] = set()
    for queue in QueueStore(data_dir, project_id).list():
        if runtime_session_id is not None and queue.runtime_session_id != runtime_session_id:
            continue
        for item in queue.items:
            if (
                item.status != "COMPLETED"
                or not item.final_case_set_id
                or item.api_operation_id in seen_operation_ids
            ):
                continue
            try:
                final_cases = workflow_store.get_final_cases(item.final_case_set_id)
            except ArtifactError:
                continue
            if final_cases.status != "READY":
                continue
            seen_operation_ids.add(item.api_operation_id)
            completed.append(CompletedProjectCases(queue=queue, item=item, final_cases=final_cases))
    return completed
