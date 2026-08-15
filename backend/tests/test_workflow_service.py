from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import AppSettings
from app.core.errors import WorkflowRunError
from app.workflow.service import WorkflowService
from app.workflow.store import WorkflowStore
from app.providers.llm import ProviderError, SecretReferenceError
from app.workflow.fingerprint import requirement_fingerprint
from app.workflow.models import WorkflowRunSnapshot
from tests.test_workflow import _project_and_operation
from tests.test_workflow import _build_workflow


class _FailingGraph:
    def invoke_nlu(self, state):
        raise RuntimeError("provider_payload password=should-not-leak")


def test_design_failure_is_persisted_without_leaking_exception_details(tmp_path: Path):
    project_service, project_id, operation = _project_and_operation(tmp_path)
    service = WorkflowService(
        project_service,
        tmp_path,
        AppSettings(data_dir=tmp_path),
    )
    service._workflow_for = lambda project: _FailingGraph()

    with pytest.raises(WorkflowRunError, match="Final Cases"):
        service.run_design(
            project_id,
            operation.operation_id,
            workflow_id="workflow-failed",
            input_document="password=also-should-not-leak",
        )

    snapshot = WorkflowStore(tmp_path, project_id).get_run("workflow-failed")
    assert snapshot.status == "FAILED"
    assert snapshot.errors == ["Workflow execution failed before Final Cases were produced."]
    assert "password" not in snapshot.model_dump_json()


def test_requirement_approval_persists_existing_workflow_snapshot(tmp_path: Path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    snapshot = workflow.invoke_nlu(
        {
            "workflow_id": "workflow-approval-persistence",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "input_document_id": "reqdoc-test",
            "input_document": "business requirement",
            "events": [],
            "errors": [],
        }
    )
    WorkflowStore(tmp_path, project_id).save_run(
        WorkflowRunSnapshot(
            workflow_id="workflow-approval-persistence",
            project_id=project_id,
            operation_id=operation.operation_id,
            source_document_id="reqdoc-test",
            status=snapshot["status"],
            requirement=snapshot["requirement"],
            evidence=snapshot["evidence"],
            test_points=snapshot["test_points"],
            events=snapshot["events"],
            errors=snapshot["errors"],
        )
    )
    service = WorkflowService(
        workflow.project_service,
        tmp_path,
        AppSettings(data_dir=tmp_path),
    )

    approval = service.approve_requirement(
        project_id,
        "workflow-approval-persistence",
        requirement_id=snapshot["requirement"].requirement_id,
        requirement_version=snapshot["requirement"].version,
        requirement_fingerprint_value=requirement_fingerprint(snapshot["requirement"]),
    )

    assert approval.status == "APPROVED"
    restored = WorkflowStore(tmp_path, project_id).get_run("workflow-approval-persistence")
    assert restored.status == "DESIGNING"
    assert restored.requirement_approval is not None


def test_provider_failure_message_keeps_safe_category_without_payload():
    message = WorkflowService._safe_failure_message(
        ProviderError("LLM provider request failed: HTTPStatusError")
    )
    assert message == "AI provider request failed (HTTPStatusError); no Final Cases were produced."
    assert "payload" not in message

    credential_message = WorkflowService._safe_failure_message(
        SecretReferenceError("secret value must not be returned")
    )
    assert "DEEPSEEK_API_KEY" in credential_message
    assert "secret value" not in credential_message
