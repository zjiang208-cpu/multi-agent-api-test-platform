from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.errors import ResourceNotFoundError
from app.evidence.providers.database import DatabaseSchemaEvidenceProvider
from app.evidence.providers.auth_fixture import AuthFixtureEvidenceProvider
from app.evidence.providers.openapi import OpenApiEvidenceProvider
from app.evidence.providers.operation_yaml import OperationYamlEvidenceProvider
from app.evidence.providers.source import JavaSpringSourceEvidenceProvider
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.evidence.registry import EvidenceRegistry
from app.models.auth import AuthProtocol
from app.models.evidence import EvidenceFact
from app.projects.service import ProjectService
from app.requirements.operation_store import OperationStore
from app.workflow.agents import LlmTelemetry, StructuredLangChainAgent
from app.workflow.auth_protocol import extract_auth_protocol, normalize_auth_text
from app.workflow.design_nodes import DesignNodesMixin
from app.workflow.graph_rules import WorkflowRulesMixin
from app.workflow.models import (
    DesignerAgentOutput,
    RequirementAgentOutput,
)
from app.workflow.state import WorkflowEvent, WorkflowState


class ApiTestWorkflow(WorkflowRulesMixin, DesignNodesMixin):
    """The one-way LangGraph design workflow up to the Human Gate."""

    def __init__(
        self,
        *,
        project_service: ProjectService,
        data_dir: Path,
        nlu_agent: StructuredLangChainAgent[RequirementAgentOutput],
        designer_agent: StructuredLangChainAgent[DesignerAgentOutput],
        reviewer_agent: StructuredLangChainAgent[ReviewerAgentOutput],
        checkpointer: MemorySaver | None = None,
        telemetry: LlmTelemetry | None = None,
    ) -> None:
        self.project_service = project_service
        self.data_dir = Path(data_dir)
        self.nlu_agent = nlu_agent
        self.designer_agent = designer_agent
        self.reviewer_agent = reviewer_agent
        self.telemetry = telemetry
        self.checkpointer = checkpointer or MemorySaver()
        self.nlu_graph = self._build_nlu_graph()
        self.design_graph = self._build_design_graph()

    def invoke(self, state: WorkflowState) -> WorkflowState:
        """Compatibility alias that stops at mandatory Human Gate #1."""

        return self.invoke_nlu(state)

    def invoke_nlu(self, state: WorkflowState) -> WorkflowState:
        """Run only the per-API NLU phase and stop before Human Gate #1."""

        config = {"configurable": {"thread_id": state["workflow_id"]}}
        return self.nlu_graph.invoke(state, config=config)

    def invoke_after_requirement_approval(self, state: WorkflowState) -> WorkflowState:
        """Resume one API from its frozen Requirement Approval snapshot."""

        if state.get("requirement_approval") is None:
            raise ValueError("Requirement Approval is required before Designer")
        config = {"configurable": {"thread_id": state["workflow_id"]}}
        return self.design_graph.invoke(state, config=config)

    def _build_nlu_graph(self):
        builder = StateGraph(WorkflowState)
        builder.add_node("document_parser", self._document_parser)
        builder.add_node("evidence_retriever", self._evidence_retriever)
        builder.add_node("nlu_agent", self._nlu_agent_node)
        builder.add_edge(START, "document_parser")
        builder.add_edge("document_parser", "evidence_retriever")
        builder.add_edge("evidence_retriever", "nlu_agent")
        builder.add_edge("nlu_agent", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _build_design_graph(self):
        builder = StateGraph(WorkflowState)
        builder.add_node("designer_agent", self._designer_agent_node)
        builder.add_node("reviewer_agent", self._reviewer_agent_node)
        builder.add_node("supplement_designer_agent", self._supplement_designer_agent_node)
        builder.add_node("local_final_validator", self._local_final_validator_node)
        builder.add_node("final_case_assembler", self._final_case_assembler)
        builder.add_edge(START, "designer_agent")
        builder.add_edge("designer_agent", "reviewer_agent")
        builder.add_conditional_edges(
            "reviewer_agent",
            self._route_after_review,
            {
                "supplement": "supplement_designer_agent",
                "finish": "final_case_assembler",
            },
        )
        builder.add_conditional_edges(
            "supplement_designer_agent",
            self._route_after_supplement,
            {
                "local_finish": "local_final_validator",
            },
        )
        builder.add_edge("local_final_validator", "final_case_assembler")
        builder.add_edge("final_case_assembler", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _document_parser(self, state: WorkflowState) -> dict[str, Any]:
        project = self.project_service.get(state["project_id"])
        operation = OperationStore(self.data_dir, state["project_id"]).get(state["operation_id"])
        if operation is None:
            raise ResourceNotFoundError(f"operation not found: {state['operation_id']}")
        input_document = state.get("input_document")
        if input_document is not None:
            input_document = input_document.strip()
            if not input_document:
                input_document = None
        return self._update(
            state,
            operation=operation,
            input_document=input_document,
            status="DOCUMENT_PARSED",
            node="document_parser",
            message=(
                f"Loaded operation {operation.operation_id} for project {project.project_id}; "
                f"requirement document={'provided' if input_document else 'not provided'}."
            ),
        )

    def _evidence_retriever(self, state: WorkflowState) -> dict[str, Any]:
        project = self.project_service.get(state["project_id"])
        operation = state["operation"]
        context = EvidenceContext(
            project_id=state["project_id"],
            operation=operation,
            settings=project.settings,
        )
        evidence = EvidenceRegistry(
            [
                OpenApiEvidenceProvider(),
                OperationYamlEvidenceProvider(),
                AuthFixtureEvidenceProvider(),
                JavaSpringSourceEvidenceProvider(),
                DatabaseSchemaEvidenceProvider(),
            ]
        ).collect(
            context,
            EvidenceQuery(include_optional=state.get("include_optional_evidence", False)),
        )
        input_document = state.get("input_document")
        document_excerpt: str | None = None
        if input_document:
            source_document_id = (
                state.get("input_document_id")
                or operation.source_document_id
                or "inline-requirement-document"
            )
            excerpt = self._operation_requirement_excerpt(operation, input_document)
            document_excerpt = self._operation_auth_context(
                operation,
                input_document,
                excerpt,
            )
            digest = sha256(
                f"{source_document_id}|{operation.operation_id}|{input_document}".encode("utf-8")
            ).hexdigest()[:32]
            document_fact = EvidenceFact(
                evidence_id=f"evidence-requirement-{digest}",
                source_type="requirement_document",
                reference=f"requirement_document:{source_document_id}",
                fact=(
                    f"Requirement document for {operation.method} {operation.path}:\n"
                    f"{excerpt}"
                ),
                operation_id=operation.operation_id,
                safe_excerpt=excerpt,
                metadata={"source_document_id": source_document_id},
            )
            evidence = evidence.model_copy(
                update={
                    "facts": [document_fact, *evidence.facts],
                    "provider_status": {
                        **evidence.provider_status,
                        "requirement_document": "collected",
                    },
                }
            )
        auth_protocol = extract_auth_protocol(
            operation=operation,
            document_excerpt=document_excerpt,
            evidence=evidence,
        )
        return self._update(
            state,
            evidence=evidence,
            auth_protocol=auth_protocol,
            status="EVIDENCE_RETRIEVED",
            node="evidence_retriever",
            message=f"Retrieved {len(evidence.facts)} evidence facts.",
        )

    def _nlu_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        operation = state["operation"]
        source_document = state.get("input_document")
        if source_document:
            operation_excerpt = self._operation_requirement_excerpt(
                operation,
                source_document,
            )
            source_document = self._operation_auth_context(
                operation,
                source_document,
                operation_excerpt,
            )
        output = self.nlu_agent.invoke(
            {
                "operation": operation,
                "current_api": operation,
                "source_document": source_document,
                "evidence": state["evidence"],
                "auth_protocol": state.get("auth_protocol", AuthProtocol()),
            }
        )
        requirement = self._normalize_requirement(output.requirement, state)
        requirement, points = self._normalize_auth_protocol_output(
            requirement,
            output.test_points,
            state.get("auth_protocol", AuthProtocol()),
            state.get("evidence"),
        )
        self._require_requirement(requirement, state)
        points = self._normalize_test_points(points, requirement, state)
        points = self._complete_explicit_numeric_boundary_points(points, requirement)
        requirement, points = self._resolve_exact_numeric_boundary_fixtures(
            requirement,
            points,
            state,
        )
        return self._update(
            state,
            requirement=requirement,
            test_points=points,
            status="WAITING_REQUIREMENT_APPROVAL",
            node="nlu_agent",
            message=(
                f"NLU Agent produced Requirement {requirement.requirement_id} and "
                f"{len(points.points)} Test Points; waiting for approval."
            ),
        )
