from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.core.errors import WorkflowRunError
from app.models.contracts import OperationContract
from app.models.evidence import EvidenceBundle
from app.models.queue import ApiProcessingItem, ApiProcessingQueue
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection
from app.workflow.models import FinalCaseSet, RequirementApproval, WorkflowRunSnapshot
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


class _ReadyRetryWorkflow:
    def __init__(self, snapshot: WorkflowRunSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def continue_after_requirement_approval(
        self,
        project_id: str,
        workflow_id: str,
    ) -> WorkflowRunSnapshot:
        self.calls += 1
        assert project_id == self.snapshot.project_id
        assert workflow_id == self.snapshot.workflow_id
        return self.snapshot.model_copy(
            update={
                "status": "FINAL_CASES_READY",
                "final_cases": FinalCaseSet(
                    final_case_set_id="final-retried",
                    requirement_id="REQ-ITEM",
                    requirement_fingerprint="fingerprint",
                    status="READY",
                ),
            }
        )


def _cached_nlu_snapshot(project_id: str, workflow_id: str) -> WorkflowRunSnapshot:
    operation = OperationContract(
        operation_id="get-item",
        method="GET",
        path="/items/{id}",
        responses=[{"status_code": 200}],
    )
    requirement = RequirementDocument(
        requirement_id="REQ-ITEM",
        source_document_id="reqdoc-cached",
        api=operation,
    )
    points = TestPointCollection(
        requirement_id="REQ-ITEM",
        requirement_version=1,
    )
    approval = RequirementApproval(
        workflow_id=workflow_id,
        project_id=project_id,
        requirement_id="REQ-ITEM",
        requirement_version=1,
        requirement_fingerprint="fingerprint",
        test_point_count=0,
        approved_at=datetime.now(timezone.utc),
    )
    return WorkflowRunSnapshot(
        workflow_id=workflow_id,
        project_id=project_id,
        operation_id="get-item",
        source_document_id="reqdoc-cached",
        status="DESIGNING",
        requirement=requirement,
        evidence=EvidenceBundle(operation_id="get-item"),
        test_points=points,
        requirement_approval=approval,
    )


def test_failed_designer_retry_reuses_persisted_nlu_snapshot(tmp_path):
    project_id = "project-cached-retry"
    run_id = "queue-cached-retry"
    workflow_id = "workflow-cached-retry"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-cached",
        selected_api_ids=["get-item"],
        status="FAILED",
        items=[
            ApiProcessingItem(
                api_operation_id="get-item",
                order=1,
                status="FAILED",
                current_stage="DESIGNER",
                workflow_id=workflow_id,
                requirement_id="REQ-ITEM",
                requirement_version=1,
                error_message="provider returned non-JSON",
            )
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    WorkflowStore(tmp_path, project_id).save_run(
        _cached_nlu_snapshot(project_id, workflow_id)
    )
    workflow = _ReadyRetryWorkflow(_cached_nlu_snapshot(project_id, workflow_id))
    service = SequentialQueueService(
        SimpleNamespace(get=lambda requested_project_id: object()),
        tmp_path,
        None,
    )
    service._workflow_service = lambda: workflow

    retried_queue, retried_snapshot = service.retry_current_design(project_id, run_id)

    assert workflow.calls == 1
    assert retried_queue.status == "READY_FOR_EXECUTION"
    assert retried_queue.items[0].status == "COMPLETED"
    assert retried_queue.items[0].final_case_set_id == "final-retried"
    assert retried_snapshot.status == "FINAL_CASES_READY"
    persisted = WorkflowStore(tmp_path, project_id).get_run(workflow_id)
    assert persisted.requirement is not None
    assert persisted.evidence is not None
    assert persisted.test_points is not None
    assert persisted.requirement_approval is not None
    assert persisted.metadata["nlu_cache_reused"] == "true"


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


def test_ready_final_cases_without_requirement_are_rejected_as_invalid_snapshot(tmp_path, monkeypatch):
    project_id = "project-invalid-ready"
    run_id = "queue-invalid-ready"
    workflow_id = "workflow-invalid-ready"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-invalid-ready",
        selected_api_ids=["get-item"],
        status="RUNNING",
        items=[
            ApiProcessingItem(
                api_operation_id="get-item",
                order=1,
                status="DESIGNING",
                current_stage="DESIGNER",
                workflow_id=workflow_id,
            )
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    snapshot = WorkflowRunSnapshot(
        workflow_id=workflow_id,
        project_id=project_id,
        operation_id="get-item",
        status="FINAL_CASES_READY",
        final_cases=FinalCaseSet(
            final_case_set_id="final-invalid-ready",
            requirement_id="REQ-ITEM",
            requirement_fingerprint="fingerprint",
            status="READY",
        ),
    )
    service = SequentialQueueService(None, tmp_path, None)
    monkeypatch.setattr(service, "get", lambda *_: queue)
    monkeypatch.setattr(service, "_workflow_service", lambda: _ClarificationWorkflow(snapshot))

    with pytest.raises(WorkflowRunError, match="missing Requirement"):
        service.continue_current_after_approval(project_id, run_id)

    persisted = QueueStore(tmp_path, project_id).get(run_id)
    assert persisted.status == "FAILED"
    assert persisted.items[0].status == "FAILED"


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


def test_blocked_queue_can_skip_current_item_and_persist_terminal_state(tmp_path, monkeypatch):
    project_id = "project-blocked-skip"
    run_id = "queue-blocked-skip"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-blocked-skip",
        selected_api_ids=["get-item"],
        status="BLOCKED",
        items=[
            ApiProcessingItem(
                api_operation_id="get-item",
                order=1,
                status="BLOCKED",
                current_stage="REVIEWER",
                workflow_id="workflow-blocked-skip",
                final_case_set_id="final-blocked-skip",
                error_message="missing deterministic fixture",
            )
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    service = SequentialQueueService(
        SimpleNamespace(get=lambda requested_project_id: object()),
        tmp_path,
        None,
    )

    skipped = service.skip_current(project_id, run_id, "accepted for later manual review")

    assert skipped.status == "SKIPPED"
    assert skipped.current_index == 1
    assert skipped.items[0].status == "SKIPPED"
    assert skipped.items[0].workflow_id == "workflow-blocked-skip"
    assert skipped.items[0].final_case_set_id == "final-blocked-skip"
    assert skipped.items[0].error_message == "accepted for later manual review"
    assert QueueStore(tmp_path, project_id).get(run_id).status == "SKIPPED"


def test_skipping_blocked_item_starts_next_item_and_keeps_completed_items_ready(tmp_path):
    project_id = "project-blocked-skip-next"
    run_id = "queue-blocked-skip-next"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-blocked-skip-next",
        selected_api_ids=["blocked-item", "pending-item"],
        status="BLOCKED",
        current_index=0,
        items=[
            ApiProcessingItem(
                api_operation_id="blocked-item",
                order=1,
                status="BLOCKED",
                current_stage="REVIEWER",
                workflow_id="workflow-blocked",
                final_case_set_id="final-blocked",
                error_message="coverage gap",
            ),
            ApiProcessingItem(
                api_operation_id="pending-item",
                order=2,
                status="PENDING",
                current_stage="NLU",
            ),
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    service = SequentialQueueService(
        SimpleNamespace(get=lambda requested_project_id: object()),
        tmp_path,
        None,
    )

    skipped = service.skip_current(project_id, run_id)

    assert skipped.status == "RUNNING"
    assert skipped.current_index == 1
    assert skipped.items[0].status == "SKIPPED"
    assert skipped.items[1].status == "NLU_RUNNING"
    assert skipped.items[1].current_stage == "NLU"

    captured: dict[str, ApiProcessingQueue] = {}

    def capture_nlu(next_queue: ApiProcessingQueue):
        captured["queue"] = next_queue
        return next_queue, None

    service._run_nlu_for_current = capture_nlu
    continued = service.continue_after_skip(project_id, run_id)

    assert continued.status == "RUNNING"
    assert continued.current_index == 1
    assert captured["queue"].current_index == 1


def test_skip_after_completed_item_marks_queue_ready_with_skips(tmp_path):
    project_id = "project-ready-with-skips"
    run_id = "queue-ready-with-skips"
    queue = ApiProcessingQueue(
        run_id=run_id,
        project_id=project_id,
        source_document_id="reqdoc-ready-with-skips",
        selected_api_ids=["completed-item", "blocked-item"],
        status="BLOCKED",
        current_index=1,
        items=[
            ApiProcessingItem(
                api_operation_id="completed-item",
                order=1,
                status="COMPLETED",
                current_stage="COMPLETED",
                final_case_set_id="final-completed",
            ),
            ApiProcessingItem(
                api_operation_id="blocked-item",
                order=2,
                status="BLOCKED",
                current_stage="REVIEWER",
            ),
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    service = SequentialQueueService(
        SimpleNamespace(get=lambda requested_project_id: object()),
        tmp_path,
        None,
    )

    skipped = service.skip_current(project_id, run_id)

    assert skipped.status == "READY_WITH_SKIPS"
    assert skipped.current_index == 2


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


def test_concurrent_queue_creation_allows_only_one_active_flow(tmp_path, monkeypatch):
    project_id = "project-create-race"
    document_id = "document-create-race"

    class ProjectServiceStub:
        @staticmethod
        def get(requested_project_id: str):
            assert requested_project_id == project_id
            return object()

    class DocumentStoreStub:
        def __init__(self, *_args):
            pass

        @staticmethod
        def get(requested_document_id: str):
            assert requested_document_id == document_id
            return object()

    class OperationStoreStub:
        def __init__(self, *_args):
            pass

        @staticmethod
        def get(operation_id: str, _runtime_session_id: str | None):
            return SimpleNamespace(
                operation_id=operation_id,
                source_document_id=document_id,
            )

    monkeypatch.setattr(
        "app.workflow.queue_service.RequirementDocumentStore",
        DocumentStoreStub,
    )
    monkeypatch.setattr("app.workflow.queue_service.OperationStore", OperationStoreStub)
    monkeypatch.setattr(
        "app.workflow.queue_service.completed_project_cases",
        lambda *_args, **_kwargs: [],
    )
    original_list = QueueStore.list

    def delayed_list(store: QueueStore):
        queues = original_list(store)
        if not queues:
            time.sleep(0.1)
        return queues

    monkeypatch.setattr(QueueStore, "list", delayed_list)

    def create_queue():
        service = SequentialQueueService(
            ProjectServiceStub(),
            tmp_path,
            None,
            runtime_session_id="runtime-create-race",
        )
        try:
            return "created", service.create(project_id, document_id, ["get-item"])
        except WorkflowRunError as exc:
            return "rejected", exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_queue(), range(2)))

    assert sorted(status for status, _ in results) == ["created", "rejected"]
    assert len(original_list(QueueStore(tmp_path, project_id))) == 1


def test_concurrent_queue_start_runs_nlu_only_once(tmp_path, monkeypatch):
    project_id = "project-start-race"
    queue = ApiProcessingQueue(
        run_id="queue-start-race",
        project_id=project_id,
        source_document_id="document-start-race",
        selected_api_ids=["get-item"],
        items=[ApiProcessingItem(api_operation_id="get-item", order=1)],
    )
    QueueStore(tmp_path, project_id).save(queue)

    class ProjectServiceStub:
        @staticmethod
        def get(requested_project_id: str):
            assert requested_project_id == project_id
            return object()

    original_get = SequentialQueueService.get

    def delayed_get(service, requested_project_id: str, run_id: str):
        current = original_get(service, requested_project_id, run_id)
        if current.status == "PENDING":
            time.sleep(0.1)
        return current

    nlu_calls = 0
    nlu_calls_lock = Lock()

    def capture_nlu(_service, current: ApiProcessingQueue):
        nonlocal nlu_calls
        with nlu_calls_lock:
            nlu_calls += 1
        return current, object()

    monkeypatch.setattr(SequentialQueueService, "get", delayed_get)
    monkeypatch.setattr(SequentialQueueService, "_run_nlu_for_current", capture_nlu)

    def start_queue():
        service = SequentialQueueService(ProjectServiceStub(), tmp_path, None)
        try:
            return "started", service.start(project_id, queue.run_id)
        except WorkflowRunError as exc:
            return "rejected", exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start_queue(), range(2)))

    assert sorted(status for status, _ in results) == ["rejected", "started"]
    assert nlu_calls == 1
