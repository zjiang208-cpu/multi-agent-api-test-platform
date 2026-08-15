from __future__ import annotations

from app.models.queue import ApiProcessingItem, ApiProcessingQueue
from app.workflow.models import FinalCaseSet, WorkflowRunSnapshot
from app.workflow.queue_service import SequentialQueueService
from app.workflow.queue_store import QueueStore
from app.workflow.project_cases import completed_project_cases
from app.workflow.store import WorkflowStore


class _ClarificationWorkflow:
    def __init__(self, snapshot: WorkflowRunSnapshot) -> None:
        self.snapshot = snapshot

    def continue_after_requirement_approval(
        self,
        project_id: str,
        workflow_id: str,
    ) -> WorkflowRunSnapshot:
        assert project_id == self.snapshot.project_id
        assert workflow_id == self.snapshot.workflow_id
        return self.snapshot


def test_clarification_is_persisted_as_blocked_instead_of_generic_failure(tmp_path, monkeypatch):
    project_id = "project-blocked"
    run_id = "queue-blocked"
    workflow_id = "workflow-blocked"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-blocked",
        selected_api_ids=["get-item"],
        status="RUNNING",
        items=[
            ApiProcessingItem(
                api_operation_id="get-item",
                order=1,
                status="DESIGNING",
                current_stage="DESIGNER",
                workflow_id=workflow_id,
                requirement_id="REQ-ITEM",
                requirement_version=1,
            )
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    final_cases = FinalCaseSet(
        final_case_set_id="final-blocked",
        requirement_id="REQ-ITEM",
        requirement_fingerprint="fingerprint",
        source_document_id="reqdoc-blocked",
        api_operation_id="get-item",
        status="NEEDS_CLARIFICATION",
        assembly_errors=["reviewer found an invalid case"],
    )
    snapshot = WorkflowRunSnapshot(
        workflow_id=workflow_id,
        project_id=project_id,
        operation_id="get-item",
        source_document_id="reqdoc-blocked",
        status="NEEDS_CLARIFICATION",
        final_cases=final_cases,
    )
    queue_service = SequentialQueueService(None, tmp_path, None)
    monkeypatch.setattr(queue_service, "get", lambda *_: queue)
    monkeypatch.setattr(
        queue_service,
        "_workflow_service",
        lambda: _ClarificationWorkflow(snapshot),
    )

    blocked_queue, returned_snapshot = queue_service.continue_current_after_approval(
        project_id,
        run_id,
    )

    assert returned_snapshot is snapshot
    assert blocked_queue.status == "BLOCKED"
    assert blocked_queue.items[0].status == "BLOCKED"
    assert blocked_queue.items[0].current_stage == "REVIEWER"
    assert blocked_queue.items[0].final_case_set_id == "final-blocked"
    assert "invalid case" in (blocked_queue.items[0].error_message or "")
    persisted = QueueStore(tmp_path, project_id).get(run_id)
    assert persisted.status == "BLOCKED"


def test_blocked_queue_can_restart_from_fresh_nlu_snapshot(tmp_path, monkeypatch):
    project_id = "project-blocked-retry"
    run_id = "queue-blocked-retry"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-blocked-retry",
        selected_api_ids=["get-item"],
        status="BLOCKED",
        items=[
            ApiProcessingItem(
                api_operation_id="get-item",
                order=1,
                status="BLOCKED",
                current_stage="REVIEWER",
                workflow_id="workflow-stale",
                requirement_id="REQ-STALE",
                requirement_version=1,
                final_case_set_id="final-stale",
                error_message="stale evidence",
            )
        ],
    )
    service = SequentialQueueService(None, tmp_path, None)
    monkeypatch.setattr(service, "get", lambda *_: queue)

    captured: dict[str, ApiProcessingQueue] = {}

    def capture_restart(restarted: ApiProcessingQueue):
        captured["queue"] = restarted
        return restarted, None

    monkeypatch.setattr(service, "_run_nlu_for_current", capture_restart)

    restarted, _ = service.start(project_id, run_id)

    item = restarted.items[0]
    assert restarted.status == "RUNNING"
    assert item.status == "NLU_RUNNING"
    assert item.current_stage == "NLU"
    assert item.workflow_id is None
    assert item.requirement_id is None
    assert item.final_case_set_id is None
    assert item.error_message is None


def test_queue_store_lists_latest_queue_first(tmp_path):
    project_id = "project-list"
    older = ApiProcessingQueue(
        run_id="queue-older",
        project_id=project_id,
        source_document_id="reqdoc-list",
        selected_api_ids=["get-item"],
        items=[ApiProcessingItem(api_operation_id="get-item", order=1)],
    )
    newer = older.model_copy(
        update={
            "run_id": "queue-newer",
            "updated_at": older.updated_at.replace(year=older.updated_at.year + 1),
        }
    )
    store = QueueStore(tmp_path, project_id)
    store.save(older)
    store.save(newer)

    assert [queue.run_id for queue in store.list()] == ["queue-newer", "queue-older"]


def test_queue_service_lists_only_current_runtime_queues(tmp_path):
    project_id = "project-runtime"

    class ProjectServiceStub:
        @staticmethod
        def get(requested_project_id: str):
            assert requested_project_id == project_id
            return object()

    current = ApiProcessingQueue(
        run_id="queue-current",
        runtime_session_id="runtime-current",
        project_id=project_id,
        source_document_id="reqdoc-runtime",
        selected_api_ids=["get-item"],
        items=[ApiProcessingItem(api_operation_id="get-item", order=1)],
    )
    previous = current.model_copy(
        update={
            "run_id": "queue-previous",
            "runtime_session_id": "runtime-previous",
        }
    )
    legacy = current.model_copy(
        update={
            "run_id": "queue-legacy",
            "runtime_session_id": None,
        }
    )
    store = QueueStore(tmp_path, project_id)
    store.save(previous)
    store.save(legacy)
    store.save(current)

    service = SequentialQueueService(
        ProjectServiceStub(),
        tmp_path,
        None,
        runtime_session_id="runtime-current",
    )

    assert [queue.run_id for queue in service.list(project_id)] == ["queue-current"]


def test_completed_project_cases_are_scoped_to_current_runtime(tmp_path):
    project_id = "project-runtime-cases"
    current_cases = FinalCaseSet(
        final_case_set_id="final-current",
        requirement_id="REQ-CURRENT",
        requirement_fingerprint="fingerprint-current",
        api_operation_id="get-current",
        status="READY",
    )
    previous_cases = FinalCaseSet(
        final_case_set_id="final-previous",
        requirement_id="REQ-PREVIOUS",
        requirement_fingerprint="fingerprint-previous",
        api_operation_id="get-previous",
        status="READY",
    )
    workflow_store = WorkflowStore(tmp_path, project_id)
    workflow_store.save_final_cases(current_cases)
    workflow_store.save_final_cases(previous_cases)

    current_queue = ApiProcessingQueue(
        run_id="queue-current-cases",
        runtime_session_id="runtime-current",
        project_id=project_id,
        source_document_id="document-current",
        selected_api_ids=["get-current"],
        status="READY_FOR_EXECUTION",
        items=[ApiProcessingItem(
            api_operation_id="get-current",
            order=1,
            status="COMPLETED",
            current_stage="COMPLETED",
            final_case_set_id=current_cases.final_case_set_id,
        )],
    )
    previous_queue = current_queue.model_copy(update={
        "run_id": "queue-previous-cases",
        "runtime_session_id": "runtime-previous",
        "source_document_id": "document-previous",
        "selected_api_ids": ["get-previous"],
        "items": [ApiProcessingItem(
            api_operation_id="get-previous",
            order=1,
            status="COMPLETED",
            current_stage="COMPLETED",
            final_case_set_id=previous_cases.final_case_set_id,
        )],
    })
    QueueStore(tmp_path, project_id).save(current_queue)
    QueueStore(tmp_path, project_id).save(previous_queue)

    visible = completed_project_cases(
        tmp_path,
        project_id,
        runtime_session_id="runtime-current",
    )

    assert [entry.final_cases.final_case_set_id for entry in visible] == ["final-current"]
