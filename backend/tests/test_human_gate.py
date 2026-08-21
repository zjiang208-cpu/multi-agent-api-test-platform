from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.executor.http import HttpExecutor
from app.models.cases import Assertion, RequestTemplate
from app.models.execution import RunResult
from app.models.projects import ProjectSettings
from app.models.queue import ApiProcessingItem, ApiProcessingQueue
from app.projects.service import ProjectService
from app.requirements.requirement_store import RequirementStore
from app.workflow.execution import (
    BatchExecutionService,
    BatchHumanGateService,
    BatchQueueExecutionService,
    HumanGateService,
)
from app.workflow.models import WorkflowRunSnapshot
from app.workflow.queue_store import QueueStore
from app.workflow.store import WorkflowStore
from tests.test_workflow import _build_workflow, _invoke_approved_workflow


def _persist_ready_workflow(tmp_path: Path):
    workflow, project_id, operation, calls = _build_workflow(tmp_path)
    state = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-human-gate",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        }
    )
    final_cases = state["final_cases"].model_copy(
        update={
            "cases": [
                state["final_cases"].cases[0].model_copy(
                    update={
                        "request": RequestTemplate(
                            method="GET",
                            path="/items/{id}",
                            path_params={"id": 1},
                        )
                    }
                ),
                state["final_cases"].cases[1].model_copy(
                    update={
                        "request": RequestTemplate(
                            method="GET",
                            path="/items/{id}",
                            path_params={"id": "missing"},
                        ),
                        "assertions": [
                            *state["final_cases"].cases[1].assertions,
                            Assertion(
                                assertion_id="ASSERT-BUSINESS",
                                type="json_value",
                                path="$.success",
                                expected=True,
                                evidence_refs=[state["evidence"].facts[0].evidence_id],
                            ),
                        ],
                    }
                ),
            ]
        }
    )
    snapshot = WorkflowRunSnapshot(
        workflow_id=state["workflow_id"],
        project_id=project_id,
        operation_id=operation.operation_id,
        status=state["status"],
        requirement=state["requirement"],
        evidence=state["evidence"],
        test_points=state["test_points"],
        draft_cases=state["draft_cases"],
        reviewer_output=state["reviewer_output"],
        final_cases=final_cases,
        events=state["events"],
    )
    store = WorkflowStore(tmp_path, project_id)
    store.save_run(snapshot)
    store.save_final_cases(final_cases)
    RequirementStore(tmp_path, project_id).save(snapshot.requirement)
    return project_id, operation, snapshot, workflow.project_service


def test_human_gate_requires_explicit_side_effect_confirmation(tmp_path):
    project_id, operation, snapshot, project_service = _persist_ready_workflow(tmp_path)
    final_cases = snapshot.final_cases.model_copy(
        update={
            "cases": [
                snapshot.final_cases.cases[0].model_copy(update={"side_effect": True}),
                snapshot.final_cases.cases[1],
            ]
        }
    )
    WorkflowStore(tmp_path, project_id).save_run(snapshot.model_copy(update={"final_cases": final_cases}))
    WorkflowStore(tmp_path, project_id).save_final_cases(final_cases)
    gate = HumanGateService(project_service, tmp_path)

    with pytest.raises(Exception, match="side-effect"):
        gate.approve(
            project_id,
            snapshot.workflow_id,
            final_case_set_id=final_cases.final_case_set_id,
            target_environment="local",
            base_url="http://127.0.0.1:8081",
            case_ids=[case.case_id for case in final_cases.cases],
            case_count=2,
            side_effect_case_ids=[],
            side_effects_confirmed=False,
        )

    approval = gate.approve(
        project_id,
        snapshot.workflow_id,
        final_case_set_id=final_cases.final_case_set_id,
        target_environment="local",
        base_url="http://127.0.0.1:8081",
        case_ids=[case.case_id for case in final_cases.cases],
        case_count=2,
        side_effect_case_ids=[final_cases.cases[0].case_id],
        side_effects_confirmed=True,
    )
    assert approval.selected_case_count == 2
    assert approval.side_effect_case_ids == [final_cases.cases[0].case_id]


def test_human_gate_rejects_remote_target_by_default(tmp_path):
    project_id, operation, snapshot, project_service = _persist_ready_workflow(tmp_path)
    gate = HumanGateService(project_service, tmp_path)

    with pytest.raises(Exception, match="remote targets are disabled"):
        gate.approve(
            project_id,
            snapshot.workflow_id,
            final_case_set_id=snapshot.final_cases.final_case_set_id,
            target_environment="remote",
            base_url="https://example.invalid",
            case_ids=[snapshot.final_cases.cases[0].case_id],
            case_count=1,
            side_effect_case_ids=[],
            side_effects_confirmed=False,
        )


@pytest.mark.asyncio
async def test_approved_batch_executes_and_auto_regression_checks_fingerprint(tmp_path):
    project_id, operation, snapshot, project_service = _persist_ready_workflow(tmp_path)
    gate = HumanGateService(project_service, tmp_path)
    approval = gate.approve(
        project_id,
        snapshot.workflow_id,
        final_case_set_id=snapshot.final_cases.final_case_set_id,
        target_environment="local",
        base_url="http://127.0.0.1:8081",
        case_ids=[case.case_id for case in snapshot.final_cases.cases],
        case_count=2,
        side_effect_case_ids=[],
        side_effects_confirmed=False,
    )

    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request.url.path.endswith("missing"):
            return httpx.Response(404, json={"success": False}, request=request)
        return httpx.Response(200, json={"success": True}, request=request)

    execution = BatchExecutionService(
        project_service,
        tmp_path,
        executor=HttpExecutor(transport=httpx.MockTransport(handler)),
    )
    run, report = await execution.execute_manual(project_id, approval.approval_id)
    assert run.approval_id == approval.approval_id
    assert run.passed_count == 1
    assert run.failed_count == 1
    assert report.total_cases == 2
    assert report.status == "mixed"

    replayed_run, replayed_report = await execution.execute_manual(
        project_id, approval.approval_id
    )
    assert replayed_run.run_id == run.run_id
    assert replayed_report.report_id == report.report_id
    assert request_count == 2
    consumed = WorkflowStore(tmp_path, project_id).get_approval(approval.approval_id)
    assert consumed.status == "CONSUMED"
    assert consumed.manual_run_id == run.run_id

    auto_run, auto_report = await execution.execute_auto_regression(project_id, approval.approval_id)
    assert auto_run.approval_id == approval.approval_id
    assert auto_report.total_cases == 2
    assert request_count == 4

    changed = snapshot.requirement.model_copy(
        update={"business_rules": ["Requirement changed after approval."]}
    )
    RequirementStore(tmp_path, project_id).save(changed)
    with pytest.raises(Exception, match="Requirement changed"):
        await execution.execute_auto_regression(project_id, approval.approval_id)


@pytest.mark.asyncio
async def test_batch_approval_is_consumed_once_and_reuses_durable_result(tmp_path):
    project_id, operation, snapshot, project_service = _persist_ready_workflow(tmp_path)
    queue = ApiProcessingQueue(
        run_id="queue-human-gate",
        project_id=project_id,
        source_document_id="document-human-gate",
        selected_api_ids=[operation.operation_id],
        status="READY_FOR_EXECUTION",
        items=[
            ApiProcessingItem(
                api_operation_id=operation.operation_id,
                order=1,
                status="COMPLETED",
                current_stage="COMPLETED",
                workflow_id=snapshot.workflow_id,
                requirement_id=snapshot.requirement.requirement_id,
                requirement_version=snapshot.requirement.version,
                final_case_set_id=snapshot.final_cases.final_case_set_id,
            )
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)
    approval = BatchHumanGateService(project_service, tmp_path).approve(
        project_id,
        queue.run_id,
        target_environment="local",
        base_url="http://127.0.0.1:8081",
        case_ids=[case.case_id for case in snapshot.final_cases.cases],
        case_count=len(snapshot.final_cases.cases),
        side_effect_case_ids=[],
        side_effects_confirmed=False,
    )
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"success": True}, request=request)

    execution = BatchQueueExecutionService(
        project_service,
        tmp_path,
        executor=HttpExecutor(transport=httpx.MockTransport(handler)),
    )
    run, report = await execution.execute_batch(project_id, approval.approval_id)
    replayed_run, replayed_report = await execution.execute_batch(
        project_id, approval.approval_id
    )

    assert replayed_run.run_id == run.run_id
    assert replayed_report.report_id == report.report_id
    assert request_count == len(snapshot.final_cases.cases)
    consumed = WorkflowStore(tmp_path, project_id).get_batch_approval(approval.approval_id)
    assert consumed.status == "CONSUMED"
    assert consumed.manual_run_id == run.run_id


@pytest.mark.asyncio
async def test_project_batch_approval_accumulates_completed_single_api_queues(tmp_path):
    project_id, operation, snapshot, project_service = _persist_ready_workflow(tmp_path)
    first_queue = ApiProcessingQueue(
        run_id="queue-first-api",
        project_id=project_id,
        source_document_id="document-first",
        selected_api_ids=[operation.operation_id],
        status="READY_FOR_EXECUTION",
        items=[
            ApiProcessingItem(
                api_operation_id=operation.operation_id,
                order=1,
                status="COMPLETED",
                current_stage="COMPLETED",
                workflow_id=snapshot.workflow_id,
                requirement_id=snapshot.requirement.requirement_id,
                requirement_version=snapshot.requirement.version,
                final_case_set_id=snapshot.final_cases.final_case_set_id,
            )
        ],
    )
    second_cases = snapshot.final_cases.model_copy(
        update={
            "final_case_set_id": "final-second-api",
            "api_operation_id": "get-second-item",
            "source_document_id": "document-second",
            "cases": [
                case.model_copy(update={"case_id": f"{case.case_id}-SECOND"})
                for case in snapshot.final_cases.cases
            ],
        }
    )
    second_queue = ApiProcessingQueue(
        run_id="queue-second-api",
        project_id=project_id,
        source_document_id="document-second",
        selected_api_ids=["get-second-item"],
        status="READY_FOR_EXECUTION",
        items=[
            ApiProcessingItem(
                api_operation_id="get-second-item",
                order=1,
                status="COMPLETED",
                current_stage="COMPLETED",
                workflow_id="workflow-second-api",
                requirement_id=second_cases.requirement_id,
                requirement_version=1,
                final_case_set_id=second_cases.final_case_set_id,
            )
        ],
    )
    WorkflowStore(tmp_path, project_id).save_final_cases(second_cases)
    QueueStore(tmp_path, project_id).save(first_queue)
    QueueStore(tmp_path, project_id).save(second_queue)

    all_case_ids = [
        *[case.case_id for case in snapshot.final_cases.cases],
        *[case.case_id for case in second_cases.cases],
    ]
    approval = BatchHumanGateService(project_service, tmp_path).approve_project(
        project_id,
        target_environment="local",
        base_url="http://127.0.0.1:8081",
        case_ids=all_case_ids,
        case_count=len(all_case_ids),
        side_effect_case_ids=[],
        side_effects_confirmed=False,
    )

    assert set(approval.queue_run_ids) == {"queue-first-api", "queue-second-api"}
    assert set(approval.source_document_ids) == {"document-first", "document-second"}
    assert set(approval.final_case_set_ids) == {
        snapshot.final_cases.final_case_set_id,
        second_cases.final_case_set_id,
    }
    assert approval.selected_case_count == len(all_case_ids)

    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"success": True}, request=request)

    execution = BatchQueueExecutionService(
        project_service,
        tmp_path,
        executor=HttpExecutor(transport=httpx.MockTransport(handler)),
    )
    run, report = await execution.execute_batch(project_id, approval.approval_id)

    assert request_count == len(all_case_ids)
    assert len(run.results) == len(all_case_ids)
    assert {result.api_operation_id for result in run.results} == {
        operation.operation_id,
        "get-second-item",
    }
    assert report.total_cases == len(all_case_ids)
    assert set(report.by_api) == {operation.operation_id, "get-second-item"}


def test_batch_approval_ignores_skipped_queue_items(tmp_path):
    project_id, operation, snapshot, project_service = _persist_ready_workflow(tmp_path)
    queue = ApiProcessingQueue(
        run_id="queue-ready-with-skips",
        project_id=project_id,
        source_document_id="document-ready-with-skips",
        selected_api_ids=[operation.operation_id, "skipped-item"],
        status="READY_WITH_SKIPS",
        current_index=2,
        items=[
            ApiProcessingItem(
                api_operation_id=operation.operation_id,
                order=1,
                status="COMPLETED",
                current_stage="COMPLETED",
                workflow_id=snapshot.workflow_id,
                requirement_id=snapshot.requirement.requirement_id,
                requirement_version=snapshot.requirement.version,
                final_case_set_id=snapshot.final_cases.final_case_set_id,
            ),
            ApiProcessingItem(
                api_operation_id="skipped-item",
                order=2,
                status="SKIPPED",
                current_stage="REVIEWER",
                error_message="coverage gap retained for review",
            ),
        ],
    )
    QueueStore(tmp_path, project_id).save(queue)

    approval = BatchHumanGateService(project_service, tmp_path).approve(
        project_id,
        queue.run_id,
        target_environment="local",
        base_url="http://127.0.0.1:8081",
        case_ids=[case.case_id for case in snapshot.final_cases.cases],
        case_count=len(snapshot.final_cases.cases),
        side_effect_case_ids=[],
        side_effects_confirmed=False,
    )

    assert approval.final_case_set_ids == [snapshot.final_cases.final_case_set_id]
    assert approval.selected_case_count == len(snapshot.final_cases.cases)
