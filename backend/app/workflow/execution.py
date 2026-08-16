from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.errors import HumanGateRequiredError, ResourceNotFoundError
from app.executor.auth import AutomaticAuthenticationError, AutomaticAuthProvider
from app.executor.http import HttpExecutor
from app.models.execution import RunResult
from app.models.reports import ReportSnapshot
from app.models.projects import ProjectSettings
from app.projects.service import ProjectService
from app.reports.service import ReportService
from app.reports.store import ReportStore
from app.requirements.requirement_store import RequirementStore
from app.requirements.yaml_store import ArtifactError
from app.runs.store import RunStore
from app.workflow.fingerprint import requirement_fingerprint
from app.workflow.models import BatchExecutionApproval, ExecutionApproval, FinalCaseSet, WorkflowRunSnapshot
from app.workflow.queue_store import QueueStore
from app.workflow.project_cases import completed_project_cases
from app.workflow.store import WorkflowStore


_APPROVAL_STATE_LOCK = RLock()


def _expects_unauthorized(case) -> bool:
    """Do not refresh credentials for an intentionally unauthenticated case."""

    return any(
        assertion.type == "status_code" and str(assertion.expected) in {"401", "403"}
        for assertion in case.assertions
    )


class HumanGateService:
    def __init__(
        self,
        project_service: ProjectService,
        data_dir: Path,
        *,
        allow_remote_targets: bool = False,
    ) -> None:
        self.project_service = project_service
        self.data_dir = Path(data_dir)
        self.allow_remote_targets = allow_remote_targets

    def approve(
        self,
        project_id: str,
        workflow_id: str,
        *,
        final_case_set_id: str,
        target_environment: str,
        base_url: str,
        case_ids: list[str],
        case_count: int,
        side_effect_case_ids: list[str],
        side_effects_confirmed: bool,
        auto_regression_allowed: bool = True,
    ) -> ExecutionApproval:
        self.project_service.get(project_id)
        snapshot = self._load_workflow(project_id, workflow_id)
        try:
            HttpExecutor(allow_remote_targets=self.allow_remote_targets).validate_target(base_url)
        except ValueError as exc:
            raise HumanGateRequiredError(str(exc)) from exc
        final_cases = snapshot.final_cases
        if final_cases is None or final_cases.status != "READY":
            raise HumanGateRequiredError(
                "only READY Final Cases can enter the Human Gate"
            )
        if final_cases.final_case_set_id != final_case_set_id:
            raise HumanGateRequiredError("final case set does not belong to the selected workflow")
        available = {case.case_id: case for case in final_cases.cases}
        selected = set(case_ids)
        if not selected:
            raise HumanGateRequiredError("at least one case must be selected")
        missing = selected - available.keys()
        if missing:
            raise ResourceNotFoundError(f"one or more cases were not found: {sorted(missing)}")
        if case_count != len(case_ids):
            raise HumanGateRequiredError("confirmed case count does not match selected cases")
        if len(set(case_ids)) != len(case_ids):
            raise HumanGateRequiredError("selected case ids must be unique")
        expected_side_effects = {
            case_id for case_id in selected if available[case_id].side_effect
        }
        if set(side_effect_case_ids) != expected_side_effects:
            raise HumanGateRequiredError(
                "the Human Gate must explicitly list every selected case marked as side-effecting"
            )
        if len(set(side_effect_case_ids)) != len(side_effect_case_ids):
            raise HumanGateRequiredError("side-effect case ids must be unique")
        if expected_side_effects and not side_effects_confirmed:
            raise HumanGateRequiredError("side-effecting cases require explicit confirmation")
        try:
            approval = ExecutionApproval(
                approval_id=f"approval-{uuid4().hex}",
                workflow_id=workflow_id,
                project_id=project_id,
                final_case_set_id=final_case_set_id,
                requirement_id=final_cases.requirement_id,
                requirement_fingerprint=final_cases.requirement_fingerprint,
                target_environment=target_environment,
                base_url=base_url,
                selected_case_ids=case_ids,
                selected_case_count=case_count,
                side_effect_case_ids=side_effect_case_ids,
                side_effects_confirmed=side_effects_confirmed,
                auto_regression_allowed=auto_regression_allowed,
                approved_at=datetime.now(timezone.utc),
            )
        except ValueError as exc:
            raise HumanGateRequiredError(str(exc)) from exc
        WorkflowStore(self.data_dir, project_id).save_approval(approval)
        return approval

    def _load_workflow(self, project_id: str, workflow_id: str) -> WorkflowRunSnapshot:
        try:
            return WorkflowStore(self.data_dir, project_id).get_run(workflow_id)
        except ArtifactError as exc:
            raise ResourceNotFoundError(f"workflow not found: {workflow_id}") from exc


class BatchExecutionService:
    def __init__(
        self,
        project_service: ProjectService,
        data_dir: Path,
        *,
        allow_remote_targets: bool = False,
        max_response_body_length: int = 12_000,
        executor: HttpExecutor | None = None,
        auth_provider: AutomaticAuthProvider | None = None,
    ) -> None:
        self.project_service = project_service
        self.data_dir = Path(data_dir)
        self.allow_remote_targets = allow_remote_targets
        self.max_response_body_length = max_response_body_length
        self.executor = executor
        self.auth_provider = auth_provider or AutomaticAuthProvider(
            allow_remote_targets=allow_remote_targets
        )

    async def execute_manual(self, project_id: str, approval_id: str) -> tuple[RunResult, ReportSnapshot]:
        approval, previous_result = self._claim_manual_approval(project_id, approval_id)
        if previous_result is not None:
            return previous_result
        try:
            run, report = await self._execute(project_id, approval, mode="manual")
        except Exception:
            self._finish_manual_approval(project_id, approval_id, status="FAILED")
            raise
        self._finish_manual_approval(
            project_id,
            approval_id,
            status="CONSUMED",
            run_id=run.run_id,
            report_id=report.report_id,
        )
        return run, report

    async def execute_auto_regression(self, project_id: str, approval_id: str) -> tuple[RunResult, ReportSnapshot]:
        approval = self._load_approval(project_id, approval_id)
        if not approval.auto_regression_allowed:
            raise HumanGateRequiredError("this approval does not allow auto-regression")
        try:
            requirement = RequirementStore(self.data_dir, project_id).get(approval.requirement_id)
        except ArtifactError as exc:
            raise HumanGateRequiredError("the approved Requirement is no longer available") from exc
        if requirement_fingerprint(requirement) != approval.requirement_fingerprint:
            raise HumanGateRequiredError(
                "Requirement changed after approval; a new Human Gate approval is required"
            )
        return await self._execute(project_id, approval, mode="auto_regression")

    async def _execute(
        self,
        project_id: str,
        approval: ExecutionApproval,
        *,
        mode: str,
    ) -> tuple[RunResult, ReportSnapshot]:
        project = self.project_service.get(project_id)
        if approval.project_id != project_id:
            raise HumanGateRequiredError("approval does not belong to this project")
        try:
            final_cases = WorkflowStore(self.data_dir, project_id).get_final_cases(
                approval.final_case_set_id
            )
        except ArtifactError as exc:
            raise ResourceNotFoundError(
                f"final case set not found: {approval.final_case_set_id}"
            ) from exc
        if (
            final_cases.status != "READY"
            or final_cases.requirement_id != approval.requirement_id
            or final_cases.requirement_fingerprint != approval.requirement_fingerprint
        ):
            raise HumanGateRequiredError("approved Final Cases are no longer executable")
        selected_ids = set(approval.selected_case_ids)
        selected_cases = [case for case in final_cases.cases if case.case_id in selected_ids]
        if len(selected_cases) != approval.selected_case_count:
            raise HumanGateRequiredError("approved case selection no longer matches Final Cases")
        settings = project.settings.model_copy(
            update={
                "sut_target": project.settings.sut_target.model_copy(
                    update={"base_url": approval.base_url}
                )
            }
        )
        executor = self.executor
        automatic_auth = executor is None
        credentials = None
        if automatic_auth:
            try:
                credentials = await self.auth_provider.resolve(
                    settings,
                    project_id=project_id,
                    base_url=str(approval.base_url),
                    cases=selected_cases,
                )
            except AutomaticAuthenticationError as exc:
                raise HumanGateRequiredError(str(exc)) from exc
            executor = HttpExecutor(
                allow_remote_targets=self.allow_remote_targets,
                max_response_body_length=self.max_response_body_length,
                auth_token=credentials.token if credentials else None,
                auth_prefix=credentials.prefix if credentials else None,
                auth_location=credentials.location if credentials else "header",
                auth_name=credentials.name if credentials else "Authorization",
            )
        results = []
        auth_refresh_attempted = False
        for case in selected_cases:
            result = await executor.execute(case, settings)
            if (
                automatic_auth
                and not auth_refresh_attempted
                and result.status_code == 401
                and not _expects_unauthorized(case)
            ):
                auth_refresh_attempted = True
                self.auth_provider.invalidate(project_id, str(approval.base_url))
                try:
                    refreshed = await self.auth_provider.resolve(
                        settings,
                        project_id=project_id,
                        base_url=str(approval.base_url),
                        cases=selected_cases,
                    )
                except AutomaticAuthenticationError:
                    refreshed = None
                if refreshed is not None and refreshed.token != (credentials.token if credentials else None):
                    credentials = refreshed
                    executor = HttpExecutor(
                        allow_remote_targets=self.allow_remote_targets,
                        max_response_body_length=self.max_response_body_length,
                        auth_token=credentials.token,
                        auth_prefix=credentials.prefix,
                        auth_location=credentials.location,
                        auth_name=credentials.name,
                    )
                    result = await executor.execute(case, settings)
            results.append(result)
        run = RunResult(
            run_id=f"run-{uuid4().hex}",
            project_id=project_id,
            requirement_id=approval.requirement_id,
            approval_id=approval.approval_id,
            target_environment=approval.target_environment,
            base_url=str(approval.base_url),
            results=results,
            passed_count=sum(item.status == "passed" for item in results),
            failed_count=sum(item.status == "failed" for item in results),
            error_count=sum(item.status == "error" for item in results),
            completed_at=datetime.now(timezone.utc),
        )
        RunStore(self.data_dir, project_id).save(run)
        report = ReportService.build(run)
        ReportStore(self.data_dir, project_id).save(report)
        return run, report

    def _load_approval(self, project_id: str, approval_id: str) -> ExecutionApproval:
        self.project_service.get(project_id)
        try:
            approval = WorkflowStore(self.data_dir, project_id).get_approval(approval_id)
        except ArtifactError as exc:
            raise ResourceNotFoundError(f"approval not found: {approval_id}") from exc
        if approval.project_id != project_id:
            raise HumanGateRequiredError("approval does not belong to this project")
        return approval

    def _claim_manual_approval(
        self,
        project_id: str,
        approval_id: str,
    ) -> tuple[ExecutionApproval, tuple[RunResult, ReportSnapshot] | None]:
        with _APPROVAL_STATE_LOCK:
            approval = self._load_approval(project_id, approval_id)
            if approval.status == "CONSUMED":
                return approval, self._load_previous_result(project_id, approval)
            if approval.status != "APPROVED":
                raise HumanGateRequiredError(
                    f"approval is {approval.status.lower()}; a new approval is required"
                )
            store = WorkflowStore(self.data_dir, project_id)
            if not store.claim_approval_execution(approval_id):
                approval = self._load_approval(project_id, approval_id)
                if approval.status == "CONSUMED":
                    return approval, self._load_previous_result(project_id, approval)
                raise HumanGateRequiredError(
                    "approval execution has already been claimed; a new approval is required"
                )
            running = approval.model_copy(
                update={
                    "status": "RUNNING",
                    "execution_updated_at": datetime.now(timezone.utc),
                }
            )
            store.save_approval(running)
            return running, None

    def _finish_manual_approval(
        self,
        project_id: str,
        approval_id: str,
        *,
        status: str,
        run_id: str | None = None,
        report_id: str | None = None,
    ) -> None:
        with _APPROVAL_STATE_LOCK:
            approval = self._load_approval(project_id, approval_id)
            updated = approval.model_copy(
                update={
                    "status": status,
                    "manual_run_id": run_id,
                    "manual_report_id": report_id,
                    "execution_updated_at": datetime.now(timezone.utc),
                }
            )
            WorkflowStore(self.data_dir, project_id).save_approval(updated)

    def _load_previous_result(
        self,
        project_id: str,
        approval: ExecutionApproval | BatchExecutionApproval,
    ) -> tuple[RunResult, ReportSnapshot]:
        if approval.manual_run_id is None or approval.manual_report_id is None:
            raise HumanGateRequiredError(
                "consumed approval has no durable result; a new approval is required"
            )
        run = RunStore(self.data_dir, project_id).get(approval.manual_run_id)
        report = ReportStore(self.data_dir, project_id).get(approval.manual_report_id)
        if run is None or report is None:
            raise HumanGateRequiredError(
                "approved execution result is unavailable; a new approval is required"
            )
        return run, report


class BatchHumanGateService:
    """Human Gate #2 for all completed API items in one Queue."""

    def __init__(
        self,
        project_service: ProjectService,
        data_dir: Path,
        *,
        allow_remote_targets: bool = False,
        runtime_session_id: str | None = None,
    ) -> None:
        self.project_service = project_service
        self.data_dir = Path(data_dir)
        self.allow_remote_targets = allow_remote_targets
        self.runtime_session_id = runtime_session_id

    def approve(
        self,
        project_id: str,
        queue_run_id: str,
        *,
        target_environment: str,
        base_url: str,
        case_ids: list[str],
        case_count: int,
        side_effect_case_ids: list[str],
        side_effects_confirmed: bool,
        auto_regression_allowed: bool = True,
    ) -> BatchExecutionApproval:
        self.project_service.get(project_id)
        queue = QueueStore(self.data_dir, project_id).get(queue_run_id)
        if queue.status not in {"READY_FOR_EXECUTION", "READY_WITH_SKIPS"}:
            raise HumanGateRequiredError("all selected APIs must complete before batch execution approval")
        final_sets: list[FinalCaseSet] = []
        for item in queue.items:
            if item.status == "SKIPPED":
                continue
            if item.status != "COMPLETED" or not item.final_case_set_id:
                raise HumanGateRequiredError("every queue item must have frozen Final Cases")
            try:
                final_sets.append(WorkflowStore(self.data_dir, project_id).get_final_cases(item.final_case_set_id))
            except ArtifactError as exc:
                raise ResourceNotFoundError(f"Final Cases not found: {item.final_case_set_id}") from exc
        if not final_sets:
            raise HumanGateRequiredError("the queue has no completed API test cases")
        return self._approve_final_sets(
            project_id,
            queue_run_id=queue_run_id,
            queue_run_ids=[queue_run_id],
            source_document_id=queue.source_document_id,
            source_document_ids=[queue.source_document_id],
            final_sets=final_sets,
            target_environment=target_environment,
            base_url=base_url,
            case_ids=case_ids,
            case_count=case_count,
            side_effect_case_ids=side_effect_case_ids,
            side_effects_confirmed=side_effects_confirmed,
            auto_regression_allowed=auto_regression_allowed,
        )

    def approve_project(
        self,
        project_id: str,
        *,
        target_environment: str,
        base_url: str,
        case_ids: list[str],
        case_count: int,
        side_effect_case_ids: list[str],
        side_effects_confirmed: bool,
        auto_regression_allowed: bool = True,
    ) -> BatchExecutionApproval:
        self.project_service.get(project_id)
        completed = completed_project_cases(
            self.data_dir,
            project_id,
            runtime_session_id=self.runtime_session_id,
        )
        if not completed:
            raise HumanGateRequiredError("the project has no completed API test cases")
        return self._approve_final_sets(
            project_id,
            queue_run_id=completed[0].queue.run_id,
            queue_run_ids=list(dict.fromkeys(entry.queue.run_id for entry in completed)),
            source_document_id=completed[0].queue.source_document_id,
            source_document_ids=list(dict.fromkeys(entry.queue.source_document_id for entry in completed)),
            final_sets=[entry.final_cases for entry in completed],
            target_environment=target_environment,
            base_url=base_url,
            case_ids=case_ids,
            case_count=case_count,
            side_effect_case_ids=side_effect_case_ids,
            side_effects_confirmed=side_effects_confirmed,
            auto_regression_allowed=auto_regression_allowed,
        )

    def _approve_final_sets(
        self,
        project_id: str,
        *,
        queue_run_id: str,
        queue_run_ids: list[str],
        source_document_id: str,
        source_document_ids: list[str],
        final_sets: list[FinalCaseSet],
        target_environment: str,
        base_url: str,
        case_ids: list[str],
        case_count: int,
        side_effect_case_ids: list[str],
        side_effects_confirmed: bool,
        auto_regression_allowed: bool,
    ) -> BatchExecutionApproval:
        try:
            HttpExecutor(allow_remote_targets=self.allow_remote_targets).validate_target(base_url)
        except ValueError as exc:
            raise HumanGateRequiredError(str(exc)) from exc
        available = {case.case_id: case for final in final_sets for case in final.cases}
        if len(available) != sum(len(final.cases) for final in final_sets):
            raise HumanGateRequiredError("case ids must be unique across the batch")
        if not case_ids or any(case_id not in available for case_id in case_ids):
            raise ResourceNotFoundError("one or more selected batch cases were not found")
        if len(set(case_ids)) != len(case_ids) or case_count != len(case_ids):
            raise HumanGateRequiredError("selected case count does not match the batch selection")
        expected_side_effects = {case_id for case_id in case_ids if available[case_id].side_effect}
        if set(side_effect_case_ids) != expected_side_effects:
            raise HumanGateRequiredError("all selected side-effecting cases must be listed")
        if expected_side_effects and not side_effects_confirmed:
            raise HumanGateRequiredError("side-effecting cases require explicit confirmation")
        approval = BatchExecutionApproval(
            approval_id=f"batch-approval-{uuid4().hex}",
            queue_run_id=queue_run_id,
            project_id=project_id,
            source_document_id=source_document_id,
            queue_run_ids=queue_run_ids,
            source_document_ids=source_document_ids,
            final_case_set_ids=[final.final_case_set_id for final in final_sets],
            requirement_fingerprints={final.requirement_id: final.requirement_fingerprint for final in final_sets},
            target_environment=target_environment,
            base_url=base_url,
            selected_case_ids=case_ids,
            selected_case_count=case_count,
            side_effect_case_ids=side_effect_case_ids,
            side_effects_confirmed=side_effects_confirmed,
            auto_regression_allowed=auto_regression_allowed,
            approved_at=datetime.now(timezone.utc),
        )
        WorkflowStore(self.data_dir, project_id).save_batch_approval(approval)
        return approval


class BatchQueueExecutionService(BatchExecutionService):
    """Deterministic batch Executor for a frozen sequential Queue."""

    async def execute_batch(self, project_id: str, approval_id: str, *, auto_regression: bool = False) -> tuple[RunResult, ReportSnapshot]:
        self.project_service.get(project_id)
        approval, previous_result = self._claim_batch_approval(
            project_id,
            approval_id,
            auto_regression=auto_regression,
        )
        if previous_result is not None:
            return previous_result
        if auto_regression and not approval.auto_regression_allowed:
            raise HumanGateRequiredError("this batch approval does not allow auto-regression")
        try:
            final_sets = [
                WorkflowStore(self.data_dir, project_id).get_final_cases(final_case_set_id)
                for final_case_set_id in approval.final_case_set_ids
            ]
            cases_by_id = {
                case.case_id: (case, final.api_operation_id or final.requirement_id)
                for final in final_sets
                for case in final.cases
            }
            if auto_regression:
                for requirement_id, fingerprint in approval.requirement_fingerprints.items():
                    requirement = RequirementStore(self.data_dir, project_id).get(requirement_id)
                    if requirement_fingerprint(requirement) != fingerprint:
                        raise HumanGateRequiredError(
                            "Requirement changed after approval; a new Human Gate approval is required"
                        )
            selected_cases = [
                cases_by_id[case_id]
                for case_id in approval.selected_case_ids
                if case_id in cases_by_id
            ]
            if len(selected_cases) != approval.selected_case_count:
                raise HumanGateRequiredError(
                    "approved batch case selection no longer matches Final Cases"
                )
            project = self.project_service.get(project_id)
            settings = project.settings.model_copy(
                update={
                    "sut_target": project.settings.sut_target.model_copy(
                        update={"base_url": approval.base_url}
                    )
                }
            )
            executor = self.executor
            automatic_auth = executor is None
            credentials = None
            if automatic_auth:
                try:
                    credentials = await self.auth_provider.resolve(
                        settings,
                        project_id=project_id,
                        base_url=str(approval.base_url),
                        cases=[case for case, _ in selected_cases],
                    )
                except AutomaticAuthenticationError as exc:
                    raise HumanGateRequiredError(str(exc)) from exc
                executor = HttpExecutor(
                    allow_remote_targets=self.allow_remote_targets,
                    max_response_body_length=self.max_response_body_length,
                    auth_token=credentials.token if credentials else None,
                    auth_prefix=credentials.prefix if credentials else None,
                    auth_location=credentials.location if credentials else "header",
                    auth_name=credentials.name if credentials else "Authorization",
                )
            results = []
            auth_refresh_attempted = False
            for case, operation_id in selected_cases:
                result = await executor.execute(case, settings)
                if (
                    automatic_auth
                    and not auth_refresh_attempted
                    and result.status_code == 401
                    and not _expects_unauthorized(case)
                ):
                    auth_refresh_attempted = True
                    self.auth_provider.invalidate(project_id, str(approval.base_url))
                    try:
                        refreshed = await self.auth_provider.resolve(
                            settings,
                            project_id=project_id,
                            base_url=str(approval.base_url),
                            cases=[candidate for candidate, _ in selected_cases],
                        )
                    except AutomaticAuthenticationError:
                        refreshed = None
                    if refreshed is not None and refreshed.token != (credentials.token if credentials else None):
                        credentials = refreshed
                        executor = HttpExecutor(
                            allow_remote_targets=self.allow_remote_targets,
                            max_response_body_length=self.max_response_body_length,
                            auth_token=credentials.token,
                            auth_prefix=credentials.prefix,
                            auth_location=credentials.location,
                            auth_name=credentials.name,
                        )
                        result = await executor.execute(case, settings)
                results.append(result.model_copy(update={"api_operation_id": operation_id}))
            run = RunResult(
                run_id=f"run-{uuid4().hex}",
                project_id=project_id,
                requirement_id="BATCH",
                queue_run_id=approval.queue_run_id,
                approval_id=approval.approval_id,
                target_environment=approval.target_environment,
                base_url=str(approval.base_url),
                results=results,
                passed_count=sum(item.status == "passed" for item in results),
                failed_count=sum(item.status == "failed" for item in results),
                error_count=sum(item.status == "error" for item in results),
                completed_at=datetime.now(timezone.utc),
            )
            RunStore(self.data_dir, project_id).save(run)
            report = ReportService.build(run)
            ReportStore(self.data_dir, project_id).save(report)
        except Exception:
            if not auto_regression:
                self._finish_batch_approval(project_id, approval_id, status="FAILED")
            raise
        if not auto_regression:
            self._finish_batch_approval(
                project_id,
                approval_id,
                status="CONSUMED",
                run_id=run.run_id,
                report_id=report.report_id,
            )
        return run, report

    def _load_batch_approval(
        self,
        project_id: str,
        approval_id: str,
    ) -> BatchExecutionApproval:
        try:
            approval = WorkflowStore(self.data_dir, project_id).get_batch_approval(approval_id)
        except ArtifactError as exc:
            raise ResourceNotFoundError(f"batch approval not found: {approval_id}") from exc
        if approval.project_id != project_id:
            raise HumanGateRequiredError("batch approval does not belong to this project")
        return approval

    def _claim_batch_approval(
        self,
        project_id: str,
        approval_id: str,
        *,
        auto_regression: bool,
    ) -> tuple[BatchExecutionApproval, tuple[RunResult, ReportSnapshot] | None]:
        with _APPROVAL_STATE_LOCK:
            approval = self._load_batch_approval(project_id, approval_id)
            if auto_regression:
                return approval, None
            if approval.status == "CONSUMED":
                return approval, self._load_previous_result(project_id, approval)
            if approval.status != "APPROVED":
                raise HumanGateRequiredError(
                    f"batch approval is {approval.status.lower()}; a new approval is required"
                )
            store = WorkflowStore(self.data_dir, project_id)
            if not store.claim_batch_approval_execution(approval_id):
                approval = self._load_batch_approval(project_id, approval_id)
                if approval.status == "CONSUMED":
                    return approval, self._load_previous_result(project_id, approval)
                raise HumanGateRequiredError(
                    "batch approval execution has already been claimed; a new approval is required"
                )
            running = approval.model_copy(
                update={
                    "status": "RUNNING",
                    "execution_updated_at": datetime.now(timezone.utc),
                }
            )
            store.save_batch_approval(running)
            return running, None

    def _finish_batch_approval(
        self,
        project_id: str,
        approval_id: str,
        *,
        status: str,
        run_id: str | None = None,
        report_id: str | None = None,
    ) -> None:
        with _APPROVAL_STATE_LOCK:
            approval = self._load_batch_approval(project_id, approval_id)
            updated = approval.model_copy(
                update={
                    "status": status,
                    "manual_run_id": run_id,
                    "manual_report_id": report_id,
                    "execution_updated_at": datetime.now(timezone.utc),
                }
            )
            WorkflowStore(self.data_dir, project_id).save_batch_approval(updated)
