from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
from weakref import WeakValueDictionary

from app.core.errors import ResourceNotFoundError, WorkflowRunError
from app.models.queue import ApiProcessingItem, ApiProcessingQueue
from app.projects.service import ProjectService
from app.requirements.document_store import RequirementDocumentStore
from app.requirements.operation_store import OperationStore
from app.workflow.fingerprint import requirement_fingerprint as compute_requirement_fingerprint
from app.workflow.models import WorkflowRunSnapshot
from app.workflow.store import WorkflowStore
from app.workflow.queue_store import QueueStore
from app.workflow.project_cases import completed_project_cases
from app.workflow.service import WorkflowService


_TRANSITION_LOCKS_GUARD = RLock()
_TRANSITION_LOCKS: WeakValueDictionary[tuple[str, str, str], RLock] = WeakValueDictionary()


def _transition_lock(data_dir: Path, project_id: str, run_id: str = "") -> RLock:
    """Return one process-local lock shared by every service instance."""

    key = (str(Path(data_dir).expanduser().resolve()), project_id, run_id)
    with _TRANSITION_LOCKS_GUARD:
        return _TRANSITION_LOCKS.setdefault(key, RLock())


class SequentialQueueService:
    """V1 strict sequential coordinator: one API reaches Reviewer before the next starts."""

    def __init__(
        self,
        project_service: ProjectService,
        data_dir: Path,
        settings,
        *,
        runtime_session_id: str | None = None,
    ) -> None:
        self.project_service = project_service
        self.data_dir = Path(data_dir)
        self.settings = settings
        self.runtime_session_id = runtime_session_id

    def create(self, project_id: str, document_id: str, operation_ids: list[str]) -> ApiProcessingQueue:
        with _transition_lock(self.data_dir, project_id):
            return self._create(project_id, document_id, operation_ids)

    def _create(self, project_id: str, document_id: str, operation_ids: list[str]) -> ApiProcessingQueue:
        self.project_service.get(project_id)
        RequirementDocumentStore(self.data_dir, project_id).get(document_id)
        operation_store = OperationStore(self.data_dir, project_id)
        active_queues = [
            queue
            for queue in QueueStore(self.data_dir, project_id).list()
            if queue.runtime_session_id == self.runtime_session_id
            and queue.status not in {
                "READY_FOR_EXECUTION",
                "READY_WITH_SKIPS",
                "SKIPPED",
                "CANCELLED",
            }
        ]
        if active_queues:
            raise WorkflowRunError("finish the current API flow before selecting another API")
        if len(operation_ids) != 1:
            raise WorkflowRunError("exactly one API Operation must be selected")
        if len(set(operation_ids)) != len(operation_ids):
            raise WorkflowRunError("selected API Operation ids must be unique")
        completed_ids = {
            entry.item.api_operation_id
            for entry in completed_project_cases(
                self.data_dir,
                project_id,
                runtime_session_id=self.runtime_session_id,
            )
        }
        for operation_id in operation_ids:
            operation = operation_store.get(operation_id, self.runtime_session_id)
            if operation is None:
                raise ResourceNotFoundError(f"operation not found: {operation_id}")
            if operation_id in completed_ids:
                raise WorkflowRunError("this API already has frozen test cases")
            if operation.source_document_id and operation.source_document_id != document_id:
                raise WorkflowRunError("selected API does not belong to the active requirement document")
        run_id = f"queue-{uuid4().hex}"
        queue = ApiProcessingQueue(
            run_id=run_id,
            runtime_session_id=self.runtime_session_id,
            project_id=project_id,
            source_document_id=document_id,
            selected_api_ids=operation_ids,
            items=[
                ApiProcessingItem(api_operation_id=operation_id, order=index)
                for index, operation_id in enumerate(operation_ids, start=1)
            ],
        )
        QueueStore(self.data_dir, project_id).save(queue)
        return queue

    def get(self, project_id: str, run_id: str) -> ApiProcessingQueue:
        self.project_service.get(project_id)
        return QueueStore(self.data_dir, project_id).get(run_id)

    def list(self, project_id: str) -> list[ApiProcessingQueue]:
        self.project_service.get(project_id)
        queues = QueueStore(self.data_dir, project_id).list()
        if self.runtime_session_id is None:
            return queues
        return [
            queue
            for queue in queues
            if queue.runtime_session_id == self.runtime_session_id
        ]

    def start(self, project_id: str, run_id: str) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        with _transition_lock(self.data_dir, project_id, run_id):
            return self._start(project_id, run_id)

    def _start(self, project_id: str, run_id: str) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        queue = self.get(project_id, run_id)
        if queue.status not in {"PENDING", "FAILED", "BLOCKED"}:
            raise WorkflowRunError(f"queue cannot start from status {queue.status}")
        return self._start_current(queue)

    def approve_current(
        self,
        project_id: str,
        run_id: str,
        *,
        requirement_id: str,
        requirement_version: int,
        requirement_fingerprint: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        with _transition_lock(self.data_dir, project_id, run_id):
            self.prepare_current_approval(
                project_id,
                run_id,
                requirement_id=requirement_id,
                requirement_version=requirement_version,
                requirement_fingerprint=requirement_fingerprint,
            )
            return self.continue_current_after_approval(project_id, run_id)

    def prepare_current_approval(
        self,
        project_id: str,
        run_id: str,
        *,
        requirement_id: str,
        requirement_version: int,
        requirement_fingerprint: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        """Persist Human Gate #1 and return before any slow model design calls."""

        with _transition_lock(self.data_dir, project_id, run_id):
            return self._prepare_current_approval(
                project_id,
                run_id,
                requirement_id=requirement_id,
                requirement_version=requirement_version,
                requirement_fingerprint=requirement_fingerprint,
            )

    def _prepare_current_approval(
        self,
        project_id: str,
        run_id: str,
        *,
        requirement_id: str,
        requirement_version: int,
        requirement_fingerprint: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        queue = self.get(project_id, run_id)
        item = self._current_item(queue)
        if item.status != "WAITING_REQUIREMENT_APPROVAL" or not item.workflow_id:
            raise WorkflowRunError("current API is not waiting for Requirement Approval")
        workflow = self._workflow_service()
        current_snapshot = WorkflowStore(self.data_dir, project_id).get_run(item.workflow_id)
        if current_snapshot.requirement is None:
            raise WorkflowRunError("current workflow has no Requirement snapshot")
        fingerprint = compute_requirement_fingerprint(current_snapshot.requirement)
        try:
            workflow.approve_requirement(
                project_id,
                item.workflow_id,
                requirement_id=requirement_id,
                requirement_version=requirement_version,
                requirement_fingerprint_value=requirement_fingerprint or fingerprint,
            )
        except WorkflowRunError:
            raise
        except Exception as exc:
            raise WorkflowRunError("Requirement Approval could not be persisted") from exc
        item = item.model_copy(update={"status": "DESIGNING", "current_stage": "DESIGNER"})
        queue = self._replace_current(queue, item).model_copy(update={"status": "RUNNING"})
        QueueStore(self.data_dir, project_id).save(queue)
        approved_snapshot = WorkflowStore(self.data_dir, project_id).get_run(item.workflow_id)
        return queue, approved_snapshot

    def continue_current_after_approval(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        """Run the bounded Designer/Reviewer chain and persist its terminal queue state."""

        with _transition_lock(self.data_dir, project_id, run_id):
            return self._continue_current_after_approval(project_id, run_id)

    def prepare_cached_design_retry(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        """Prepare a Designer/Reviewer retry without running NLU again.

        NLU artifacts are durable workflow data, not an in-memory optimization:
        the requirement, evidence, test points and approval are loaded from the
        persisted workflow snapshot and kept intact while downstream artifacts
        are cleared for a fresh Designer/Reviewer attempt.
        """

        with _transition_lock(self.data_dir, project_id, run_id):
            return self._prepare_cached_design_retry(project_id, run_id)

    def retry_current_design(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        """Retry the current downstream design chain using cached NLU output."""

        with _transition_lock(self.data_dir, project_id, run_id):
            self._prepare_cached_design_retry(project_id, run_id)
            return self._continue_current_after_approval(project_id, run_id)

    def _prepare_cached_design_retry(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        queue = self.get(project_id, run_id)
        item = self._current_item(queue)
        if queue.status not in {"FAILED", "BLOCKED"}:
            raise WorkflowRunError(
                f"cached design retry requires a FAILED or BLOCKED queue, got {queue.status}"
            )
        if item.status not in {"FAILED", "BLOCKED"}:
            raise WorkflowRunError("current API is not eligible for a downstream retry")
        if item.current_stage not in {"DESIGNER", "REVIEWER"} or not item.workflow_id:
            raise WorkflowRunError(
                "cached NLU retry is only available after NLU has produced a workflow snapshot"
            )

        store = WorkflowStore(self.data_dir, project_id)
        try:
            snapshot = store.get_run(item.workflow_id)
        except Exception as exc:
            raise WorkflowRunError(
                "cached NLU artifacts are unavailable; restart NLU to create a fresh snapshot"
            ) from exc
        if (
            snapshot.requirement is None
            or snapshot.evidence is None
            or snapshot.test_points is None
            or snapshot.requirement_approval is None
        ):
            raise WorkflowRunError(
                "cached NLU artifacts are incomplete; restart NLU to create a fresh snapshot"
            )

        retry_snapshot = snapshot.model_copy(
            update={
                "status": "DESIGNING",
                "draft_cases": None,
                "reviewer_output": None,
                "final_cases": None,
                "errors": [],
                "events": [
                    *snapshot.events,
                    {
                        "node": "cached_nlu_retry",
                        "status": "DESIGNING",
                        "message": "reusing persisted NLU artifacts",
                    },
                ][-100:],
                "metadata": {
                    **snapshot.metadata,
                    "nlu_cache_reused": "true",
                    "nlu_cache_workflow_id": snapshot.workflow_id,
                },
            }
        )
        store.save_run(retry_snapshot)

        retry_item = item.model_copy(
            update={
                "status": "DESIGNING",
                "current_stage": "DESIGNER",
                "final_case_set_id": None,
                "error_message": None,
            }
        )
        retry_queue = self._replace_current(queue, retry_item).model_copy(
            update={"status": "RUNNING"}
        )
        QueueStore(self.data_dir, project_id).save(retry_queue)
        return retry_queue, retry_snapshot

    def skip_current(self, project_id: str, run_id: str, reason: str | None = None) -> ApiProcessingQueue:
        """Skip a blocked API while preserving its workflow for later review.

        Skipping is intentionally separate from retrying: the blocked workflow
        and its draft Final Cases remain available for audit, while the queue
        can move on to the next API (or become a terminal skipped queue when
        this is the last item).
        """

        with _transition_lock(self.data_dir, project_id, run_id):
            queue = self.get(project_id, run_id)
            if queue.status != "BLOCKED":
                raise WorkflowRunError("only a blocked queue can skip its current API")
            item = self._current_item(queue)
            if item.status != "BLOCKED":
                raise WorkflowRunError("only a blocked API can be skipped")
            message = (
                (reason or "").strip()
                or (item.error_message or "").strip()
                or "Skipped after clarification was required"
            )
            skipped = item.model_copy(
                update={
                    "status": "SKIPPED",
                    "error_message": message[:2000],
                }
            )
            queue = self._replace_current(queue, skipped)
            next_index = queue.current_index + 1
            if next_index >= len(queue.items):
                has_completed = any(candidate.status == "COMPLETED" for candidate in queue.items)
                terminal_status = "READY_WITH_SKIPS" if has_completed else "SKIPPED"
                queue = queue.model_copy(
                    update={
                        "current_index": next_index,
                        "status": terminal_status,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            else:
                next_item = queue.items[next_index].model_copy(
                    update={
                        "status": "NLU_RUNNING",
                        "current_stage": "NLU",
                        "workflow_id": None,
                        "requirement_id": None,
                        "requirement_version": None,
                        "final_case_set_id": None,
                        "error_message": None,
                    }
                )
                queue = self._replace_item(queue, next_index, next_item).model_copy(
                    update={"current_index": next_index, "status": "RUNNING"}
                )
            QueueStore(self.data_dir, project_id).save(queue)
            return queue

    def continue_after_skip(self, project_id: str, run_id: str) -> ApiProcessingQueue:
        """Start NLU for the next queue item after a skip transition."""

        with _transition_lock(self.data_dir, project_id, run_id):
            queue = self.get(project_id, run_id)
            if queue.status != "RUNNING":
                return queue
            current = self._current_item(queue)
            if current.status != "NLU_RUNNING":
                raise WorkflowRunError("queue is not ready to continue after skip")
            next_queue, _ = self._run_nlu_for_current(queue)
            return next_queue

    def _continue_current_after_approval(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        queue = self.get(project_id, run_id)
        item = self._current_item(queue)
        if item.status != "DESIGNING" or not item.workflow_id:
            raise WorkflowRunError("current API is not ready for Designer processing")
        workflow = self._workflow_service()
        try:
            snapshot = workflow.continue_after_requirement_approval(project_id, item.workflow_id)
        except Exception as exc:
            failed_item = item.model_copy(update={"status": "FAILED", "error_message": str(exc)})
            failed_queue = self._replace_current(queue, failed_item).model_copy(
                update={"status": "FAILED", "updated_at": datetime.now(timezone.utc)}
            )
            QueueStore(self.data_dir, project_id).save(failed_queue)
            raise
        if snapshot.status == "NEEDS_CLARIFICATION" and snapshot.final_cases is not None:
            details = snapshot.final_cases.assembly_errors or snapshot.final_cases.remaining_gaps
            message = "; ".join(details[:10]) or "Final Cases require clarification"
            blocked_item = item.model_copy(
                update={
                    "status": "BLOCKED",
                    "current_stage": "REVIEWER",
                    "requirement_id": (
                        snapshot.requirement.requirement_id if snapshot.requirement else item.requirement_id
                    ),
                    "requirement_version": (
                        snapshot.requirement.version if snapshot.requirement else item.requirement_version
                    ),
                    "final_case_set_id": snapshot.final_cases.final_case_set_id,
                    "error_message": message,
                }
            )
            blocked_queue = self._replace_current(queue, blocked_item).model_copy(
                update={"status": "BLOCKED"}
            )
            QueueStore(self.data_dir, project_id).save(blocked_queue)
            return blocked_queue, snapshot
        if snapshot.status != "FINAL_CASES_READY" or snapshot.final_cases is None:
            failed_item = item.model_copy(update={"status": "FAILED", "error_message": "Final Cases were not ready"})
            failed_queue = self._replace_current(queue, failed_item).model_copy(update={"status": "FAILED"})
            QueueStore(self.data_dir, project_id).save(failed_queue)
            raise WorkflowRunError("Reviewer did not produce READY Final Cases")
        if snapshot.requirement is None:
            message = "Final Cases snapshot is missing Requirement"
            failed_item = item.model_copy(update={"status": "FAILED", "error_message": message})
            failed_queue = self._replace_current(queue, failed_item).model_copy(
                update={"status": "FAILED", "updated_at": datetime.now(timezone.utc)}
            )
            QueueStore(self.data_dir, project_id).save(failed_queue)
            raise WorkflowRunError(message)
        completed_item = item.model_copy(
            update={
                "status": "COMPLETED",
                "current_stage": "COMPLETED",
                "requirement_id": snapshot.requirement.requirement_id,
                "requirement_version": snapshot.requirement.version,
                "final_case_set_id": snapshot.final_cases.final_case_set_id,
            }
        )
        queue = self._replace_current(queue, completed_item)
        next_index = queue.current_index + 1
        if next_index >= len(queue.items):
            has_skips = any(item.status == "SKIPPED" for item in queue.items)
            queue = queue.model_copy(
                update={
                    "current_index": next_index,
                    "status": "READY_WITH_SKIPS" if has_skips else "READY_FOR_EXECUTION",
                }
            )
            QueueStore(self.data_dir, project_id).save(queue)
            return queue, snapshot
        next_item = queue.items[next_index].model_copy(update={"status": "NLU_RUNNING", "current_stage": "NLU"})
        queue = self._replace_item(queue, next_index, next_item).model_copy(
            update={"current_index": next_index, "status": "RUNNING"}
        )
        QueueStore(self.data_dir, project_id).save(queue)
        return self._run_nlu_for_current(queue)

    def _start_current(self, queue: ApiProcessingQueue) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        current = self._current_item(queue)
        if current.status in {"PENDING", "FAILED", "BLOCKED"}:
            current = current.model_copy(
                update={
                    "status": "NLU_RUNNING",
                    "current_stage": "NLU",
                    "workflow_id": None,
                    "requirement_id": None,
                    "requirement_version": None,
                    "final_case_set_id": None,
                    "error_message": None,
                }
            )
            queue = self._replace_current(queue, current).model_copy(update={"status": "RUNNING"})
            QueueStore(self.data_dir, queue.project_id).save(queue)
        return self._run_nlu_for_current(queue)

    def _run_nlu_for_current(self, queue: ApiProcessingQueue) -> tuple[ApiProcessingQueue, WorkflowRunSnapshot]:
        item = self._current_item(queue)
        document = RequirementDocumentStore(self.data_dir, queue.project_id).get(queue.source_document_id)
        workflow = self._workflow_service()
        try:
            snapshot = workflow.run_nlu(
                queue.project_id,
                item.api_operation_id,
                input_document_id=queue.source_document_id,
                input_document=document.content,
            )
        except Exception as exc:
            failed = item.model_copy(update={"status": "FAILED", "error_message": str(exc)})
            queue = self._replace_current(queue, failed).model_copy(update={"status": "FAILED"})
            QueueStore(self.data_dir, queue.project_id).save(queue)
            raise
        waiting = item.model_copy(
            update={
                "status": "WAITING_REQUIREMENT_APPROVAL",
                "current_stage": "REQUIREMENT_APPROVAL",
                "workflow_id": snapshot.workflow_id,
                "requirement_id": snapshot.requirement.requirement_id if snapshot.requirement else None,
                "requirement_version": snapshot.requirement.version if snapshot.requirement else None,
            }
        )
        queue = self._replace_current(queue, waiting).model_copy(update={"status": "WAITING_REQUIREMENT_APPROVAL"})
        QueueStore(self.data_dir, queue.project_id).save(queue)
        return queue, snapshot

    def _workflow_service(self) -> WorkflowService:
        return WorkflowService(self.project_service, self.data_dir, self.settings)

    @staticmethod
    def _current_item(queue: ApiProcessingQueue) -> ApiProcessingItem:
        if queue.current_index >= len(queue.items):
            raise WorkflowRunError("queue has no current API")
        return queue.items[queue.current_index]

    @staticmethod
    def _replace_current(queue: ApiProcessingQueue, item: ApiProcessingItem) -> ApiProcessingQueue:
        return SequentialQueueService._replace_item(queue, queue.current_index, item)

    @staticmethod
    def _replace_item(queue: ApiProcessingQueue, index: int, item: ApiProcessingItem) -> ApiProcessingQueue:
        items = [*queue.items]
        items[index] = item
        return queue.model_copy(update={"items": items, "updated_at": datetime.now(timezone.utc)})
