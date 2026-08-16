from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import AppSettings
from app.core.errors import DomainError, WorkflowRunError
from app.models.projects import TestProject
from app.projects.service import ProjectService
from app.providers.llm import (
    CallBudget,
    OpenAICompatibleProvider,
    ProviderError,
    SecretReferenceError,
)
from app.providers.config import resolve_llm_config
from app.requirements.requirement_store import RequirementStore
from app.requirements.operation_store import OperationStore
from app.testpoints.store import TestPointStore
from app.workflow.agents import LlmTelemetry, provider_agent
from app.workflow.fingerprint import requirement_fingerprint
from app.workflow.graph import ApiTestWorkflow
from app.workflow.models import (
    DesignerAgentOutput,
    RequirementAgentOutput,
    ReviewerAgentOutput,
    RequirementApproval,
    WorkflowRunSnapshot,
)
from app.workflow.prompts import (
    DESIGNER_AGENT_SYSTEM,
    DESIGNER_PROMPT,
    NLU_PROMPT,
    PROMPT_MANIFEST,
    REQUIREMENT_AGENT_SYSTEM,
    REVIEWER_AGENT_SYSTEM,
    REVIEWER_PROMPT,
    WORKFLOW_PROMPT_VERSION,
)
from app.workflow.store import WorkflowStore


class WorkflowConfigurationError(DomainError):
    status_code = 503
    code = "workflow_not_configured"


class WorkflowService:
    def __init__(self, project_service: ProjectService, data_dir: Path, settings: AppSettings) -> None:
        self.project_service = project_service
        self.data_dir = Path(data_dir)
        self.settings = settings

    def run_design(
        self,
        project_id: str,
        operation_id: str,
        *,
        include_optional_evidence: bool = False,
        input_document_id: str | None = None,
        input_document: str | None = None,
        workflow_id: str | None = None,
    ) -> WorkflowRunSnapshot:
        """Compatibility endpoint that now stops at mandatory Human Gate #1."""

        return self.run_nlu(
            project_id,
            operation_id,
            input_document_id=input_document_id,
            input_document=input_document,
            include_optional_evidence=include_optional_evidence,
            workflow_id=workflow_id,
        )

    def run_nlu(
        self,
        project_id: str,
        operation_id: str,
        *,
        input_document_id: str | None,
        input_document: str | None,
        include_optional_evidence: bool = False,
        workflow_id: str | None = None,
    ) -> WorkflowRunSnapshot:
        """Run one API through NLU and stop at Human Gate #1."""

        project = self.project_service.get(project_id)
        workflow_id = workflow_id or f"workflow-{uuid4().hex}"
        graph = self._workflow_for(project)
        initial_state = {
            "workflow_id": workflow_id,
            "project_id": project_id,
            "operation_id": operation_id,
            "include_optional_evidence": include_optional_evidence,
            "input_document_id": input_document_id,
            "input_document": input_document,
            "events": [],
            "errors": [],
        }
        try:
            state = graph.invoke_nlu(initial_state)
        except DomainError:
            raise
        except Exception as exc:
            message = self._safe_failure_message(exc)
            snapshot = WorkflowRunSnapshot(
                workflow_id=workflow_id,
                project_id=project_id,
                operation_id=operation_id,
                source_document_id=input_document_id,
                status="FAILED",
                errors=[message],
                events=[{"node": "nlu", "status": "FAILED", "message": message}],
                metadata={
                    **self._metadata(project, input_document=input_document, input_document_id=input_document_id),
                    **self._telemetry_metadata(graph),
                },
            )
            WorkflowStore(self.data_dir, project_id).save_run(snapshot)
            raise WorkflowRunError(message) from exc
        snapshot = WorkflowRunSnapshot(
            workflow_id=workflow_id,
            project_id=project_id,
            operation_id=operation_id,
            source_document_id=input_document_id,
            status=state.get("status", "FAILED"),
            requirement=state.get("requirement"),
            evidence=state.get("evidence"),
            test_points=state.get("test_points"),
            errors=state.get("errors", []),
            events=state.get("events", []),
            metadata={
                **self._metadata(project, input_document=input_document, input_document_id=input_document_id),
                **self._telemetry_metadata(graph),
            },
        )
        if snapshot.requirement:
            RequirementStore(self.data_dir, project_id).save(snapshot.requirement)
        if snapshot.test_points:
            TestPointStore(self.data_dir, project_id).save(snapshot.test_points)
        WorkflowStore(self.data_dir, project_id).save_run(snapshot)
        return snapshot

    def approve_requirement(
        self,
        project_id: str,
        workflow_id: str,
        *,
        requirement_id: str,
        requirement_version: int,
        requirement_fingerprint_value: str,
    ) -> RequirementApproval:
        project = self.project_service.get(project_id)
        store = WorkflowStore(self.data_dir, project_id)
        snapshot = store.get_run(workflow_id)
        if snapshot.status != "WAITING_REQUIREMENT_APPROVAL":
            raise WorkflowRunError("only a workflow waiting for Requirement Approval can be approved")
        if snapshot.requirement is None or snapshot.test_points is None:
            raise WorkflowRunError("Requirement and Test Points are required before approval")
        if snapshot.requirement.requirement_id != requirement_id:
            raise WorkflowRunError("Requirement Approval does not match the current workflow")
        if snapshot.requirement.version != requirement_version:
            raise WorkflowRunError("Requirement version changed before approval")
        if requirement_fingerprint(snapshot.requirement) != requirement_fingerprint_value:
            raise WorkflowRunError("Requirement fingerprint does not match the displayed snapshot")
        approval = RequirementApproval(
            workflow_id=workflow_id,
            project_id=project_id,
            requirement_id=requirement_id,
            requirement_version=requirement_version,
            requirement_fingerprint=requirement_fingerprint_value,
            test_point_count=len(snapshot.test_points.points),
            approved_at=datetime.now(timezone.utc),
        )
        approved_snapshot = snapshot.model_copy(update={"status": "DESIGNING", "requirement_approval": approval})
        store.save_run(approved_snapshot)
        store.save_requirement_approval(approval)
        return approval

    def continue_after_requirement_approval(
        self,
        project_id: str,
        workflow_id: str,
    ) -> WorkflowRunSnapshot:
        project = self.project_service.get(project_id)
        store = WorkflowStore(self.data_dir, project_id)
        snapshot = store.get_run(workflow_id)
        if snapshot.requirement_approval is None:
            raise WorkflowRunError("Requirement Approval is required before Designer")
        if snapshot.requirement is None or snapshot.test_points is None or snapshot.evidence is None:
            raise WorkflowRunError("approved workflow is missing NLU artifacts")
        operation = OperationStore(self.data_dir, project_id).get(snapshot.operation_id)
        if operation is None:
            raise WorkflowRunError("selected Operation is no longer available")
        if requirement_fingerprint(snapshot.requirement) != snapshot.requirement_approval.requirement_fingerprint:
            raise WorkflowRunError("Requirement changed after approval")
        graph = self._workflow_for(project)
        state = {
            "workflow_id": snapshot.workflow_id,
            "project_id": project_id,
            "operation_id": snapshot.operation_id,
            "input_document_id": snapshot.source_document_id,
            "operation": operation,
            "evidence": snapshot.evidence,
            "requirement": snapshot.requirement,
            "test_points": snapshot.test_points,
            "requirement_approval": snapshot.requirement_approval,
            "events": snapshot.events,
            "errors": snapshot.errors,
            "status": "DESIGNING",
        }
        try:
            result = graph.invoke_after_requirement_approval(state)
        except Exception as exc:
            message = self._safe_failure_message(exc)
            # Persist downstream telemetry even when Designer/Reviewer fails.
            # This makes structured-output retries observable and allows the
            # queue UI/reporting layer to distinguish model retries from a
            # failure before the graph started.
            failed_snapshot = snapshot.model_copy(
                update={
                    "status": "FAILED",
                    "errors": [message],
                    "events": [
                        *snapshot.events,
                        {"node": "designer_reviewer", "status": "FAILED", "message": message},
                    ],
                    "metadata": {
                        **snapshot.metadata,
                        **self._telemetry_metadata(graph),
                    },
                }
            )
            store.save_run(failed_snapshot)
            raise WorkflowRunError(message) from exc
        completed = WorkflowRunSnapshot(
            workflow_id=snapshot.workflow_id,
            project_id=project_id,
            operation_id=snapshot.operation_id,
            source_document_id=snapshot.source_document_id,
            status=result.get("status", "FAILED"),
            requirement=snapshot.requirement,
            evidence=snapshot.evidence,
            test_points=snapshot.test_points,
            draft_cases=result.get("draft_cases"),
            reviewer_output=result.get("reviewer_output"),
            final_cases=result.get("final_cases"),
            requirement_approval=snapshot.requirement_approval,
            errors=result.get("errors", []),
            events=result.get("events", []),
            metadata={
                **snapshot.metadata,
                **self._telemetry_metadata(graph),
            },
        )
        if completed.draft_cases:
            from app.cases.store import CaseStore

            CaseStore(self.data_dir, project_id).save(completed.draft_cases)
        store.save_run(completed)
        if completed.final_cases:
            store.save_final_cases(completed.final_cases)
        return completed

    @staticmethod
    def _safe_failure_message(exc: Exception) -> str:
        """Keep provider payloads and validation details out of the API/artifact."""

        if isinstance(exc, SecretReferenceError):
            return "AI provider credential is not configured; expected the DEEPSEEK_API_KEY environment variable."
        if isinstance(exc, ProviderError):
            provider_message = str(exc)
            if provider_message.startswith("LLM provider request failed:"):
                category = provider_message.split(":", 1)[1].strip()
                return f"AI provider request failed ({category}); no Final Cases were produced."
            if provider_message.startswith("provider did not return JSON"):
                return "AI provider returned a non-JSON response; no Final Cases were produced."
            if provider_message.startswith("provider returned invalid JSON"):
                return "AI provider returned invalid JSON; no Final Cases were produced."
            if provider_message.startswith("provider output failed schema validation"):
                return "AI provider output did not match the required structured schema; no Final Cases were produced."
            if provider_message.startswith("LLM call budget exceeded"):
                return "AI provider call budget was exceeded; no Final Cases were produced."
            return "AI provider failed; no Final Cases were produced."
        if exc.__class__.__module__.startswith("app.providers"):
            return "AI provider failed; no Final Cases were produced."
        if isinstance(exc, (ValueError, TypeError)):
            known_validation_messages = (
                "requirement API operation_id does not match selected operation",
                "requirement referenced unknown evidence",
                "NLU test points requirement_id does not match requirement",
                "test point output requirement_id does not match input",
                "reviewer referenced unknown test points",
                "invalid workflow cases:",
            )
            if any(str(exc).startswith(prefix) for prefix in known_validation_messages):
                return f"Workflow validation failed: {str(exc)}"
            return "Workflow validation failed; no Final Cases were produced."
        return "Workflow execution failed before Final Cases were produced."

    @staticmethod
    def _metadata(project: TestProject, *, input_document: str | None, input_document_id: str | None) -> dict[str, str]:
        return {
            "graph": "langgraph",
            "prompt_version": WORKFLOW_PROMPT_VERSION,
            **PROMPT_MANIFEST,
            "llm_call_budget": str(project.settings.llm.call_budget),
            "execution_gate": "human",
            "input_document": "provided" if input_document else "not_provided",
            "input_document_id": input_document_id or "not_available",
        }

    @staticmethod
    def _telemetry_metadata(graph) -> dict[str, str]:
        telemetry = getattr(graph, "telemetry", None)
        return telemetry.metadata() if telemetry is not None else {}

    def get_run(self, project_id: str, workflow_id: str) -> WorkflowRunSnapshot:
        self.project_service.get(project_id)
        return WorkflowStore(self.data_dir, project_id).get_run(workflow_id)

    def _workflow_for(self, project: TestProject) -> ApiTestWorkflow:
        profile = project.settings.llm
        llm = resolve_llm_config(self.settings, profile)
        if not llm.complete:
            raise WorkflowConfigurationError(
                "LangGraph AI workflow requires an enabled LLM profile, model, base_url and env secret reference"
            )
        provider = OpenAICompatibleProvider(
            base_url=llm.base_url,
            model=llm.model,
            api_key_ref=llm.api_key_ref,
        )
        budget = CallBudget(max_calls=profile.call_budget)
        telemetry = LlmTelemetry()
        return ApiTestWorkflow(
            project_service=self.project_service,
            data_dir=self.data_dir,
            nlu_agent=provider_agent(
                provider,
                system_prompt=REQUIREMENT_AGENT_SYSTEM,
                response_model=RequirementAgentOutput,
                budget=budget,
                max_attempts=NLU_PROMPT.definition.retry.max_attempts,
                telemetry=telemetry,
                stage="nlu",
            ),
            designer_agent=provider_agent(
                provider,
                system_prompt=DESIGNER_AGENT_SYSTEM,
                response_model=DesignerAgentOutput,
                budget=budget,
                max_attempts=DESIGNER_PROMPT.definition.retry.max_attempts,
                telemetry=telemetry,
                stage="designer",
            ),
            reviewer_agent=provider_agent(
                provider,
                system_prompt=REVIEWER_AGENT_SYSTEM,
                response_model=ReviewerAgentOutput,
                budget=budget,
                max_attempts=REVIEWER_PROMPT.definition.retry.max_attempts,
                telemetry=telemetry,
                stage="reviewer",
            ),
            telemetry=telemetry,
        )
