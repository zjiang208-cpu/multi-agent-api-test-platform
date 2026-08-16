from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.cases.validator import validate_case
from app.core.errors import ResourceNotFoundError
from app.evidence.providers.database import DatabaseFixtureResolver, DatabaseSchemaEvidenceProvider
from app.evidence.providers.auth_fixture import AuthFixtureEvidenceProvider
from app.evidence.providers.openapi import OpenApiEvidenceProvider
from app.evidence.providers.operation_yaml import OperationYamlEvidenceProvider
from app.evidence.providers.source import JavaSpringSourceEvidenceProvider
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.evidence.registry import EvidenceRegistry
from app.models.cases import CaseSet, TestCase
from app.models.auth import AuthProtocol
from app.models.evidence import EvidenceBundle, EvidenceFact
from app.models.requirements import RequirementDocument, RequirementEvidenceRef
from app.models.testpoints import TestPoint, TestPointCollection
from app.projects.service import ProjectService
from app.providers.llm import SecretReferenceError
from app.requirements.operation_store import OperationStore
from app.workflow.agents import LlmTelemetry, StructuredLangChainAgent
from app.workflow.auth_protocol import extract_auth_protocol, normalize_auth_text
from app.workflow.fingerprint import requirement_fingerprint
from app.workflow.models import (
    DesignerAgentOutput,
    FinalCaseSet,
    RequirementAgentOutput,
    ReviewerAgentOutput,
)
from app.workflow.prompts import DESIGNER_PROMPT
from app.workflow.state import WorkflowEvent, WorkflowState


_EXACT_FIXTURE_IN_TEXT = re.compile(
    r"\$DB_FIXTURE\[(present|missing):([A-Za-z0-9_]+):([A-Za-z0-9_]+):(-?\d+)\]"
)
_AUTH_PLACEHOLDER_MARKERS = ("<redacted>", "<token>", "${token}", "$TOKEN", "YOUR_TOKEN")


class ApiTestWorkflow:
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

    @staticmethod
    def _operation_requirement_excerpt(operation, document: str) -> str:
        """Return only the current operation's requirement section.

        A bare ``document.find(operation.path)`` is unsafe for documents that
        contain related paths such as ``/items`` and ``/items/{item_id}``: it can select
        the first occurrence and leak another operation's response contract into
        the current NLU prompt. Prefer the source line range recorded during API
        discovery, then fall back to an exact method/path anchor.
        """

        lines = document.splitlines()
        line_count = len(lines)
        for source in operation.source_refs:
            if source.source_document_id and source.source_document_id != operation.source_document_id:
                continue
            start = source.start_line or 0
            end = source.end_line or 0
            reference = source.reference or ""
            has_specific_range = ":lines:" in reference or start > 1 or end < line_count
            if has_specific_range and 1 <= start <= end <= line_count:
                return "\n".join(lines[start - 1 : end]).strip()[:9_000]

        method = re.escape(operation.method)
        path = re.escape(operation.path)
        path_pattern = rf"{path}(?![A-Za-z0-9_/{{])"
        exact_line = re.compile(rf"(?i)\b{method}\b.*{path_pattern}|{path_pattern}.*\b{method}\b")

        def section_excerpt(anchor_index: int) -> str:
            # If the document has Markdown headings, keep the current heading
            # section instead of prepending a neighbouring operation's rules.
            start = max(0, anchor_index - 12)
            for candidate in range(anchor_index - 1, max(-1, anchor_index - 80), -1):
                if lines[candidate].lstrip().startswith("#"):
                    start = candidate
                    break
            end = min(line_count, anchor_index + 80)
            for candidate in range(anchor_index + 1, min(line_count, anchor_index + 160)):
                if lines[candidate].lstrip().startswith("#"):
                    end = candidate
                    break
            return "\n".join(lines[start:end]).strip()[:9_000]

        for index, line in enumerate(lines):
            if exact_line.search(line):
                return section_excerpt(index)

        # Markdown requirements often list the method in a heading/table row
        # and put the path on a separate line. Match the complete path in that
        # case, while rejecting a shorter path that is only a prefix of a
        # parameterized sibling (for example ``/items`` in ``/items/{item_id}``).
        path_only = re.compile(path_pattern, re.IGNORECASE)
        for index, line in enumerate(lines):
            if path_only.search(line):
                return section_excerpt(index)

        for source in operation.source_refs:
            if source.source_text and operation.path in source.source_text:
                return source.source_text[:9_000]
        return document[:9_000]

    @staticmethod
    def _operation_auth_context(
        operation,
        document: str,
        operation_excerpt: str,
    ) -> str:
        """Add document-level auth protocol rules to the selected operation excerpt.

        API discovery intentionally narrows the business excerpt to one operation.
        Authentication conventions are often declared once near the document top,
        so retain only headings that explicitly describe shared protocol rules and
        never append neighbouring operation sections.
        """

        lines = document.splitlines()
        global_sections: list[str] = []
        heading_pattern = re.compile(
            r"(?i)(?:当前|通用|公共|全局).*(?:协议|认证|鉴权|约定|规则)"
            r"|(?:协议|认证|鉴权).*(?:约定|规则|策略)"
            r"|auth(?:entication)?\s+(?:protocol|policy|convention)"
        )
        operation_start = min(
            (
                source.start_line
                for source in operation.source_refs
                if source.start_line and source.start_line >= 1
            ),
            default=len(lines) + 1,
        )
        for index, line in enumerate(lines):
            if (
                index + 1 >= operation_start
                or not line.lstrip().startswith("#")
                or not heading_pattern.search(line)
            ):
                continue
            end = len(lines)
            for candidate in range(index + 1, len(lines)):
                if lines[candidate].lstrip().startswith("#"):
                    end = candidate
                    break
            section = "\n".join(lines[index:end]).strip()
            if section:
                global_sections.append(section[:4_000])

        chunks = [*global_sections, operation_excerpt]
        return "\n\n".join(dict.fromkeys(chunk for chunk in chunks if chunk))[:9_000]

    def _nlu_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        output = self.nlu_agent.invoke(
            {
                "operation": state["operation"],
                "current_api": state["operation"],
                "source_document": state.get("input_document"),
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

    def _designer_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        output = self.designer_agent.invoke(
            {
                "mode": "initial",
                "operation": state["operation"],
                "requirement": state["requirement"],
                "test_points": state["test_points"],
                "evidence": self._downstream_evidence(state),
            }
        )
        draft = self._strip_unrequested_schema_assertions(
            self._canonicalize_redacted_auth_cases(
                self._normalize_case_evidence(output.draft_cases, state), state
            ),
            state["requirement"],
        ).model_copy(
            update={
                "prompt_version": (
                    f"{DESIGNER_PROMPT.definition.version}@{DESIGNER_PROMPT.sha256[:12]}"
                )
            }
        )
        valid_cases, designer_notes = self._partition_valid_cases(
            draft.cases, state, source="initial"
        )
        valid_cases = self._merge_cross_cutting_contract_cases(valid_cases)
        draft = draft.model_copy(update={"cases": valid_cases})
        return self._update(
            state,
            draft_cases=draft,
            designer_notes=designer_notes,
            status="DRAFT_CASES_READY",
            node="designer_agent",
            message=(
                f"Designer Agent produced {len(draft.cases)} draft cases."
                f"{self._metric_suffix(self.designer_agent)}"
            ),
        )

    def _reviewer_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        output = self.reviewer_agent.invoke(
            {
                "review_stage": "initial",
                "operation": state["operation"],
                "requirement": state["requirement"],
                "test_points": state["test_points"],
                "draft_cases": state["draft_cases"],
                "evidence": self._downstream_evidence(state),
            }
        )
        self._validate_review_output(output, state)
        return self._update(
            state,
            reviewer_output=output,
            node="reviewer_agent",
            message=(
                f"Reviewer Agent completed semantic review and proposed "
                f"{len(output.suggested_case_specs)} bounded case specifications."
                f"{self._metric_suffix(self.reviewer_agent)}"
            ),
        )

    @staticmethod
    def _route_after_review(state: WorkflowState) -> str:
        return "supplement" if state["reviewer_output"].suggested_case_specs else "finish"

    def _supplement_designer_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        review = state["reviewer_output"]
        output = self.designer_agent.invoke(
            {
                "mode": "supplement",
                "operation": state["operation"],
                "requirement": state["requirement"],
                "test_points": state["test_points"],
                "evidence": self._downstream_evidence(state),
                "existing_cases": state["draft_cases"],
                "review_feedback": review,
            }
        )
        supplemental_set = self._strip_unrequested_schema_assertions(
            self._canonicalize_redacted_auth_cases(
                self._normalize_case_evidence(output.draft_cases, state), state
            ),
            state["requirement"],
        )
        supplemental_cases = [
            case.model_copy(update={"source": "reviewer_added"})
            for case in supplemental_set.cases
        ]
        supplement_notes: list[str] = list(state.get("designer_notes", []))
        if len(supplemental_cases) > len(review.suggested_case_specs):
            supplement_notes.append(
                "Supplement Designer exceeded Reviewer case specification limit; "
                "extra cases were discarded."
            )
            supplemental_cases = supplemental_cases[: len(review.suggested_case_specs)]
        existing_ids = {case.case_id for case in state["draft_cases"].cases}
        existing_semantics = {
            self._case_semantic_key(case): case.case_id for case in state["draft_cases"].cases
        }
        retained_supplements: list[TestCase] = []
        for case in supplemental_cases:
            if case.case_id in existing_ids:
                supplement_notes.append(
                    f"Skipped duplicate supplemental case ID: {case.case_id}"
                )
                continue
            semantic_key = self._case_semantic_key(case)
            if semantic_key in existing_semantics:
                supplement_notes.append(
                    "Skipped semantic duplicate supplemental case: "
                    f"{case.case_id} duplicates {existing_semantics[semantic_key]}"
                )
                continue
            existing_ids.add(case.case_id)
            existing_semantics[semantic_key] = case.case_id
            retained_supplements.append(case)
        required_points = {
            point_id
            for spec in review.suggested_case_specs
            for point_id in spec.target_test_point_ids
        }
        supplied_points = {
            point_id
            for case in [*state["draft_cases"].cases, *retained_supplements]
            for point_id in case.test_point_ids
        }
        uncovered_targets = sorted(required_points - supplied_points)
        if uncovered_targets:
            supplement_notes.append(
                "Supplement Designer did not cover Reviewer targets: "
                f"{uncovered_targets}"
            )
        retained_supplements, validation_notes = self._partition_valid_cases(
            retained_supplements, state, source="reviewer_added"
        )
        supplement_notes.extend(validation_notes)
        return self._update(
            state,
            supplemental_cases=retained_supplements,
            supplement_notes=supplement_notes,
            status="REVIEWING",
            node="supplement_designer_agent",
            message=(
                f"Designer produced {len(retained_supplements)} bounded supplemental cases; "
                f"{len(supplement_notes)} validation notes were recorded."
                f"{self._metric_suffix(self.designer_agent)}"
            ),
        )

    def _route_after_supplement(self, state: WorkflowState) -> str:
        # The repair budget is one supplement pass. Any remaining uncertainty is
        # preserved as deterministic gaps instead of starting a second Reviewer
        # model call.
        return "local_finish"

    def _local_final_validator_node(self, state: WorkflowState) -> dict[str, Any]:
        review = state["reviewer_output"]
        supplemental_cases = state.get("supplemental_cases", [])
        all_cases = [*state["draft_cases"].cases, *supplemental_cases]
        covered_points = {
            point_id for case in all_cases for point_id in case.test_point_ids
        }
        unresolved_targets: set[str] = set()
        deterministic_gaps: list[str] = []
        for spec in review.suggested_case_specs:
            spec_gaps = self._supplement_spec_gaps(spec, all_cases)
            if not spec_gaps:
                continue
            unresolved_targets.update(spec.target_test_point_ids)
            deterministic_gaps.append(
                f"Bounded repair could not close {spec.spec_id}: "
                + "; ".join(spec_gaps)
            )
        remaining_gaps = list(review.remaining_gaps)
        remaining_gaps.extend(deterministic_gaps)
        locally_final = review.model_copy(
            update={
                "missing_test_point_ids": list(
                    dict.fromkeys(
                        [
                            *[
                                point_id
                                for point_id in review.missing_test_point_ids
                                if point_id not in covered_points
                            ],
                            *sorted(unresolved_targets),
                        ]
                    )
                ),
                "suggested_case_specs": [],
                "remaining_gaps": list(dict.fromkeys(remaining_gaps)),
            }
        )
        return self._update(
            state,
            reviewer_output=locally_final,
            status="REVIEWING",
            node="local_final_validator",
            message=(
                "Deterministic validation completed the single bounded supplement pass; "
                "remaining gaps were retained without another Reviewer model call."
            ),
        )

    @staticmethod
    def _downstream_evidence(state: WorkflowState) -> EvidenceBundle:
        """Send only NLU-selected evidence to Designer/Reviewer.

        The durable snapshot keeps every collected fact for auditability. Downstream
        agents only need facts referenced by the approved Requirement and Test Points;
        resending schemas for unrelated allowlisted tables adds latency without adding
        support for the current cases.
        """

        evidence = state["evidence"]
        referenced_ids = {
            reference.evidence_id for reference in state["requirement"].evidence_refs
        }
        referenced_ids.update(
            evidence_id
            for point in state["test_points"].points
            for evidence_id in point.evidence_refs
        )
        if not referenced_ids:
            return evidence
        filtered = [
            fact
            for fact in evidence.facts
            if fact.evidence_id in referenced_ids or fact.source_type == "auth_provider"
        ]
        return evidence.model_copy(update={"facts": filtered}) if filtered else evidence

    @classmethod
    def _supplement_spec_gaps(cls, spec, cases: list[TestCase]) -> list[str]:
        """Return deterministic reasons a bounded supplement did not close a spec."""

        target_points = set(spec.target_test_point_ids)
        candidate_cases = [
            case for case in cases if target_points.intersection(case.test_point_ids)
        ]
        covered_points = {
            point_id for case in candidate_cases for point_id in case.test_point_ids
        }
        gaps: list[str] = []
        uncovered = sorted(target_points - covered_points)
        if uncovered:
            gaps.append(f"target Test Points remain uncovered: {uncovered}")
        case_evidence = {
            evidence_id
            for case in candidate_cases
            for evidence_id in [
                *case.evidence_refs,
                *(ref for assertion in case.assertions for ref in assertion.evidence_refs),
            ]
        }
        missing_evidence = sorted(set(spec.evidence_refs) - case_evidence)
        if missing_evidence:
            gaps.append(f"required evidence is not referenced: {missing_evidence}")
        missing_assertions = [
            required
            for required in spec.required_assertions
            if not cls._required_assertion_is_observed(required, candidate_cases)
        ]
        if missing_assertions:
            gaps.append(f"required assertions are not observable: {missing_assertions}")
        return gaps

    @staticmethod
    def _required_assertion_is_observed(required: str, cases: list[TestCase]) -> bool:
        """Conservatively map a Reviewer assertion request to executable assertions.

        Unknown natural-language requirements deliberately return False so the
        deterministic validator preserves the gap instead of guessing coverage.
        """

        text = required.casefold()
        assertions = [assertion for case in cases for assertion in case.assertions]
        recognized = False

        status_codes = {int(value) for value in re.findall(r"(?<!\d)([1-5]\d{2})(?!\d)", text)}
        if status_codes:
            recognized = True
            if not any(
                assertion.type == "status_code" and assertion.expected in status_codes
                for assertion in assertions
            ):
                return False
        elif "http" in text or "status code" in text or "状态码" in text:
            recognized = True
            if not any(assertion.type == "status_code" for assertion in assertions):
                return False

        paths = set(re.findall(r"\$\.[A-Za-z0-9_.\[\]-]+", required))
        if paths:
            recognized = True
            actual_paths = {assertion.path for assertion in assertions if assertion.path}
            if not paths.issubset(actual_paths):
                return False

        assertion_type_hints = {
            "response_schema": ("schema", "结构", "字段契约"),
            "header_value": ("header", "响应头"),
            "json_exists": ("exists", "存在"),
            "json_array_sorted": ("json_array_sorted", "array sorted", "排序", "有序"),
            "json_type": ("json type", "类型"),
            "json_contains": ("contains", "包含"),
        }
        for assertion_type, hints in assertion_type_hints.items():
            if any(hint in text for hint in hints):
                recognized = True
                compatible_types = {assertion_type}
                if assertion_type == "response_schema":
                    compatible_types.add("json_type")
                if not any(assertion.type in compatible_types for assertion in assertions):
                    return False

        for field_name in ("success", "errormsg", "data", "total"):
            if field_name in text:
                recognized = True
                field_assertions = [
                    assertion
                    for assertion in assertions
                    if assertion.path
                    and assertion.path.casefold().rstrip(".").split(".")[-1] == field_name
                ]
                if not field_assertions:
                    return False
                if "false" in text and not any(
                    assertion.expected is False for assertion in field_assertions
                ):
                    return False
                if "true" in text and not any(
                    assertion.expected is True for assertion in field_assertions
                ):
                    return False
                literal_values = [
                    value
                    for value in re.findall(r"[`'\"]([^`'\"]+)[`'\"]", required)
                    if not value.startswith("$.")
                    and value.casefold() not in {field_name, f"$.{field_name}"}
                ]
                if literal_values and not all(
                    any(str(assertion.expected) == value for assertion in field_assertions)
                    for value in literal_values
                ):
                    return False
        return recognized

    @staticmethod
    def _metric_suffix(agent: StructuredLangChainAgent[Any]) -> str:
        metrics = agent.last_metrics
        if not metrics:
            return ""
        return (
            " LLM metrics: "
            f"calls={len(metrics)}, "
            f"duration_ms={sum(metric.duration_ms for metric in metrics)}, "
            f"input_chars={sum(metric.input_chars for metric in metrics)}, "
            f"output_chars={sum(metric.output_chars for metric in metrics)}."
        )

    @staticmethod
    def _has_unresolved_authentication(case: TestCase, project_settings) -> bool:
        """Detect model-redacted credentials without treating the case as invalid.

        A missing project auth reference is an execution configuration gap. The
        request design and its test-point coverage remain useful and should stay
        visible for the human gate instead of being discarded by assembly.
        """

        if project_settings.sut_target.auth_ref:
            return False
        authorization_values = [
            value
            for name, value in case.request.headers.items()
            if name.casefold() == "authorization"
        ]
        if not authorization_values:
            return False
        haystack = " ".join(
            [*case.preconditions, *case.steps, *authorization_values]
        ).casefold()
        return any(marker.casefold() in haystack for marker in _AUTH_PLACEHOLDER_MARKERS)

    @classmethod
    def _canonicalize_redacted_auth_cases(
        cls,
        case_set: CaseSet,
        state: WorkflowState,
    ) -> CaseSet:
        """Replace model-redacted negative credentials with safe local fixtures.

        The LLM input is intentionally redacted for safety.  A negative 401/403
        case still needs a deterministic invalid credential, however, so restore
        only the safe placeholder and keep the real token local to the executor.
        """

        fixtures = cls._auth_fixture_evidence(state.get("evidence"))
        fixture = fixtures.get("nonexistent") or fixtures.get("expired")
        if fixture is None:
            return case_set
        fixture_id, placeholder = fixture
        protocol = state.get("auth_protocol", AuthProtocol())
        replacement = placeholder
        if protocol.status == "explicit" and protocol.prefix:
            replacement = f"{protocol.prefix} {placeholder}"
        changed_cases: list[TestCase] = []
        for case in case_set.cases:
            is_unauthorized = any(
                assertion.type == "status_code"
                and str(assertion.expected) in {"401", "403"}
                for assertion in case.assertions
            )
            if not is_unauthorized:
                changed_cases.append(case)
                continue
            headers = dict(case.request.headers)
            changed = False
            for name, value in list(headers.items()):
                if name.casefold() != protocol.header_name.casefold():
                    continue
                if any(marker.casefold() in value.casefold() for marker in _AUTH_PLACEHOLDER_MARKERS):
                    headers[name] = replacement
                    changed = True
            if not changed:
                changed_cases.append(case)
                continue
            changed_cases.append(
                case.model_copy(
                    update={
                        "request": case.request.model_copy(update={"headers": headers}),
                        "evidence_refs": list(dict.fromkeys([*case.evidence_refs, fixture_id])),
                    }
                )
            )
        return case_set.model_copy(update={"cases": changed_cases})

    @staticmethod
    def _strip_authentication_placeholder(case: TestCase) -> TestCase:
        """Remove a redacted Authorization header so configured auth can be injected."""

        headers = {
            name: value
            for name, value in case.request.headers.items()
            if name.casefold() != "authorization"
            or not any(
                marker.casefold() in value.casefold()
                for marker in _AUTH_PLACEHOLDER_MARKERS
            )
        }
        if headers == case.request.headers:
            return case
        return case.model_copy(
            update={
                "request": case.request.model_copy(update={"headers": headers}),
            }
        )

    def _final_case_assembler(self, state: WorkflowState) -> dict[str, Any]:
        project = self.project_service.get(state["project_id"])
        requirement = state["requirement"]
        draft = state["draft_cases"]
        review = state["reviewer_output"]
        supplemental_cases = state.get("supplemental_cases", [])
        cases: list[TestCase] = []
        seen_ids: set[str] = set()
        seen_semantics: dict[str, str] = {}
        assembly_errors: list[str] = []
        remaining_gaps = list(review.remaining_gaps)
        remaining_gaps.extend(state.get("designer_notes", []))
        remaining_gaps.extend(state.get("supplement_notes", []))
        retained_added_ids: list[str] = []
        invalid_case_ids = set(review.invalid_case_ids)
        removed_invalid_case_ids: list[str] = []
        retained_auth_case_ids: list[str] = []
        unsupported_assertion_ids = set(review.unsupported_assertion_ids)
        fixture_resolver = DatabaseFixtureResolver()
        known_points = {point.point_id for point in state["test_points"].points}
        known_evidence = {fact.evidence_id for fact in state["evidence"].facts}
        for case, is_supplemental in [
            *((case, False) for case in draft.cases),
            *((case, True) for case in supplemental_cases),
        ]:
            if case.case_id in invalid_case_ids:
                if self._has_unresolved_authentication(case, project.settings):
                    case = self._strip_authentication_placeholder(case)
                    retained_auth_case_ids.append(case.case_id)
                    remaining_gaps.append(
                        f"Retained {case.case_id}; authentication will be obtained automatically at execution when the target supports local login."
                    )
                else:
                    deterministic_errors = validate_case(
                        case,
                        known_test_points=known_points,
                        known_evidence=known_evidence,
                        operation=state["operation"],
                    )
                    if deterministic_errors:
                        removed_invalid_case_ids.append(case.case_id)
                        remaining_gaps.append(
                            f"Removed Reviewer-invalid case before final assembly: {case.case_id}"
                        )
                        continue
                    # A Reviewer semantic concern (for example, an assertion
                    # that is too weak) is not a structural invalidity. Keep the
                    # executable Case and expose the concern as a warning.
                    remaining_gaps.append(
                        f"Reviewer marked {case.case_id} for review, but deterministic validation passed; Case retained."
                    )
            unsupported_in_case = sorted(
                assertion.assertion_id
                for assertion in case.assertions
                if assertion.assertion_id in unsupported_assertion_ids
            )
            if unsupported_in_case:
                supported_assertions = [
                    assertion
                    for assertion in case.assertions
                    if assertion.assertion_id not in unsupported_assertion_ids
                ]
                # Reviewer findings are scoped to the offending assertions. Keep
                # the Case when another executable assertion remains; only discard
                # a Case whose entire assertion set is unusable.
                remaining_gaps.append(
                    "Removed Reviewer-unsupported assertions from "
                    f"{case.case_id}: {unsupported_in_case}"
                )
                if not supported_assertions:
                    remaining_gaps.append(
                        f"Removed Case with no executable assertions after Reviewer review: {case.case_id}"
                    )
                    continue
                case = case.model_copy(update={"assertions": supported_assertions})
            if case.case_id in seen_ids:
                remaining_gaps.append(f"Removed duplicate case ID: {case.case_id}")
                continue
            try:
                case = fixture_resolver.resolve_case(case, project.settings)
            except (ValueError, SecretReferenceError) as exc:
                remaining_gaps.append(
                    f"Removed case with unresolved local database fixture: {case.case_id} -> {exc}"
                )
                continue
            semantic_key = self._case_semantic_key(case)
            if semantic_key in seen_semantics:
                remaining_gaps.append(
                    "Removed semantic duplicate case: "
                    f"{case.case_id} duplicates {seen_semantics[semantic_key]}"
                )
                continue
            seen_ids.add(case.case_id)
            seen_semantics[semantic_key] = case.case_id
            cases.append(case)
            if is_supplemental:
                retained_added_ids.append(case.case_id)

        covered_points = {point_id for case in cases for point_id in case.test_point_ids}
        expected_points = {point.point_id for point in state["test_points"].points}
        missing_points = sorted(expected_points - covered_points)
        if not expected_points:
            assembly_errors.append("no test points were generated")
        if not cases:
            assembly_errors.append("no test cases were generated")
        # Coverage gaps are review findings, not a reason to discard every
        # executable Case. They remain visible as warnings and can be handled by
        # selecting the generated cases at the Human Gate.
        if missing_points:
            remaining_gaps.append(f"Test points still uncovered: {', '.join(missing_points)}")
        if review.missing_test_point_ids:
            remaining_gaps.append(
                "Reviewer reported semantically uncovered test points: "
                f"{review.missing_test_point_ids}"
            )
        if review.semantic_gaps:
            remaining_gaps.extend(
                f"Reviewer semantic gap: {gap}" for gap in review.semantic_gaps
            )
        if removed_invalid_case_ids:
            remaining_gaps.append(
                f"Reviewer-invalid cases were removed: {removed_invalid_case_ids}"
            )
        if retained_auth_case_ids:
            remaining_gaps.append(
                "Authentication will be resolved automatically for retained cases when possible; "
                "an explicit auth_ref is used as fallback: "
                f"{retained_auth_case_ids}"
            )
        if review.duplicate_case_ids:
            remaining_gaps.append(
                f"Reviewer reported duplicate cases; deterministic deduplication was applied: "
                f"{review.duplicate_case_ids}"
            )
        if review.unsupported_assertion_ids:
            remaining_gaps.append(
                "Reviewer-unsupported assertions were removed or isolated at assertion level: "
                f"{review.unsupported_assertion_ids}"
            )
        if review.suggested_case_specs:
            remaining_gaps.append(
                "Bounded repair limit reached; unresolved case specifications require manual "
                f"follow-up: {[spec.spec_id for spec in review.suggested_case_specs]}"
            )

        unresolved_questions = list(
            dict.fromkeys(
                [*requirement.unresolved_questions, *review.unresolved_questions]
            )
        )
        # Requirement Approval is the human decision for unresolved business
        # questions. Keep questions and reviewer gaps visible on Final Cases,
        # then let the second Human Gate decide which generated Cases to execute.
        # A partial review finding must not hide otherwise executable Cases;
        # only an empty generated Case set is a hard blocker.
        status = "READY" if not assembly_errors else "NEEDS_CLARIFICATION"
        final_cases = FinalCaseSet(
            final_case_set_id=f"final-{uuid4().hex}",
            requirement_id=requirement.requirement_id,
            requirement_fingerprint=requirement_fingerprint(requirement),
            source_document_id=state.get("input_document_id"),
            api_operation_id=state["operation"].operation_id,
            cases=cases,
            added_case_ids=retained_added_ids,
            remaining_gaps=list(dict.fromkeys(remaining_gaps)),
            unresolved_questions=unresolved_questions,
            status=status,
            assembly_errors=assembly_errors,
        )
        return self._update(
            state,
            final_cases=final_cases,
            status="FINAL_CASES_READY" if status == "READY" else "NEEDS_CLARIFICATION",
            node="final_case_assembler",
            message=f"Final Cases assembled with status {status}.",
        )

    @staticmethod
    def _normalize_requirement(requirement: RequirementDocument, state: WorkflowState) -> RequirementDocument:
        """Keep the selected Operation and source document as deterministic workflow anchors.

        The LLM extracts business semantics, but it must not be allowed to change which
        API the user selected. This also makes the Operation YAML and business-document
        paths behave identically when the model paraphrases an operation identifier.
        """

        operation = state["operation"]
        evidence = state.get("evidence")
        evidence_by_id = {fact.evidence_id: fact for fact in evidence.facts} if evidence else {}
        evidence_by_reference = {fact.reference: fact for fact in evidence.facts} if evidence else {}
        evidence_refs = []
        unresolved_questions = list(requirement.unresolved_questions)
        for evidence_ref in requirement.evidence_refs:
            fact = evidence_by_id.get(evidence_ref.evidence_id) or evidence_by_reference.get(evidence_ref.reference)
            if fact is None:
                unresolved_questions.append("NLU Agent 产生了无法在当前 Evidence 快照中定位的引用，需要人工确认。")
                continue
            evidence_refs.append(
                evidence_ref.model_copy(
                    update={
                        "evidence_id": fact.evidence_id,
                        "source_type": fact.source_type,
                        "reference": fact.reference,
                    }
                )
            )
        return requirement.model_copy(
            update={
                "api": operation,
                "source_document_id": state.get("input_document_id") or operation.source_document_id,
                "evidence_refs": evidence_refs,
                "unresolved_questions": list(dict.fromkeys(unresolved_questions)),
            }
        )

    @staticmethod
    def _normalize_auth_protocol_output(
        requirement: RequirementDocument,
        points: TestPointCollection,
        protocol: AuthProtocol,
        evidence: EvidenceBundle | None = None,
    ) -> tuple[RequirementDocument, TestPointCollection]:
        """Bind model-authored wording to the selected operation's auth evidence."""

        changed = False
        requirement_updates: dict[str, Any] = {"auth_protocol": protocol}

        def normalize_values(values: list[str]) -> list[str]:
            nonlocal changed
            normalized: list[str] = []
            for value in values:
                updated, value_changed = normalize_auth_text(value, protocol)
                changed = changed or value_changed
                normalized.append(updated)
            return normalized

        for field_name in (
            "preconditions",
            "business_rules",
            "expected_behaviors",
            "conflicts",
        ):
            requirement_updates[field_name] = normalize_values(
                list(getattr(requirement, field_name))
            )

        normalized_points: list[TestPoint] = []
        for point in points.points:
            title, title_changed = normalize_auth_text(point.title, protocol)
            action, action_changed = normalize_auth_text(point.action, protocol)
            expected, expected_changed = normalize_auth_text(point.expected_result, protocol)
            changed = changed or title_changed or action_changed or expected_changed
            normalized_points.append(
                point.model_copy(
                    update={
                        "title": title,
                        "action": action,
                        "expected_result": expected,
                    }
                )
            )

        unresolved_questions = list(requirement.unresolved_questions)
        fixture_by_kind = ApiTestWorkflow._auth_fixture_evidence(evidence)
        normalized_points = ApiTestWorkflow._merge_auth_negative_points(
            normalized_points,
            fixture_by_kind,
        )
        combined_auth_semantics = ApiTestWorkflow._has_combined_auth_semantics(
            requirement_updates
        )
        if combined_auth_semantics:
            requirement_updates["expected_behaviors"] = (
                ApiTestWorkflow._collapse_combined_auth_behaviors(
                    requirement_updates["expected_behaviors"]
                )
            )
            normalized_points = [
                (
                    point.model_copy(
                        update={
                            "title": "过期/不存在 Token 返回 401",
                            "expected_result": "返回 HTTP 401，通常无响应体。",
                        }
                    )
                    if ApiTestWorkflow._auth_negative_fixture_kind(point)
                    in {"expired", "nonexistent", "combined"}
                    and re.search(r"\b401\b", point.expected_result)
                    else point
                )
                for point in normalized_points
            ]
        requirement_evidence_refs = list(requirement.evidence_refs)
        for index, point in enumerate(normalized_points):
            fixture_kind = ApiTestWorkflow._auth_negative_fixture_kind(point)
            if fixture_kind is None:
                continue
            fixture = (
                fixture_by_kind.get("nonexistent") or fixture_by_kind.get("expired")
                if fixture_kind == "combined"
                else fixture_by_kind.get(fixture_kind)
            )
            if fixture is None:
                label = "过期/不存在" if fixture_kind == "combined" else (
                    "过期" if fixture_kind == "expired" else "不存在"
                )
                unresolved_questions.append(
                    f"当前接口明确要求{label} Token 负例，"
                    f"但项目尚未配置对应 Token 夹具；请配置后再执行该 Test Point。"
                )
                continue
            fixture_id, placeholder = fixture
            action = point.action
            if placeholder not in action:
                action = f"{action.rstrip('。')}；鉴权值使用 {placeholder}。"
            normalized_points[index] = point.model_copy(
                update={
                    "action": action,
                    "evidence_refs": list(dict.fromkeys([*point.evidence_refs, fixture_id])),
                }
            )
            if not any(item.evidence_id == fixture_id for item in requirement_evidence_refs):
                fact = next(
                    fact for fact in (evidence.facts if evidence else []) if fact.evidence_id == fixture_id
                )
                requirement_evidence_refs.append(
                    RequirementEvidenceRef(
                        evidence_id=fact.evidence_id,
                        source_type=fact.source_type,
                        reference=fact.reference,
                        confidence=fact.confidence,
                    )
                )
        if combined_auth_semantics and (
            fixture_by_kind.get("nonexistent") or fixture_by_kind.get("expired")
        ):
            unresolved_questions = [
                question
                for question in unresolved_questions
                if not re.search(r"(?:过期|expired).*?(?:夹具|fixture)", question, re.IGNORECASE)
            ]
        requirement_updates["evidence_refs"] = requirement_evidence_refs
        if changed and protocol.status == "explicit" and protocol.prefix is None:
            unresolved_questions.append(
                "模型输出曾为当前接口补充不一致的 Token 前缀，已按当前接口证据校正为无前缀。"
            )
        if changed and protocol.status in {"unknown", "conflict"}:
            unresolved_questions.append(
                "模型输出自行选择了具体 Token 前缀，但当前接口证据未能确认该前缀；已改为项目配置的认证凭据。"
            )
        if protocol.status == "conflict":
            unresolved_questions.extend(protocol.conflicts)
        if protocol.conflicts:
            unresolved_questions.extend(protocol.conflicts)
        requirement_updates["unresolved_questions"] = list(dict.fromkeys(unresolved_questions))
        if requirement_updates["unresolved_questions"] and requirement.confidence == "confirmed":
            requirement_updates["confidence"] = "question"

        return requirement.model_copy(update=requirement_updates), points.model_copy(
            update={"points": normalized_points}
        )

    @staticmethod
    def _has_combined_auth_semantics(requirement_updates: dict[str, Any]) -> bool:
        text = " ".join(
            value
            for field_name in (
                "business_rules",
                "expected_behaviors",
                "unresolved_questions",
            )
            for value in requirement_updates.get(field_name, [])
        )
        has_expired = bool(re.search(r"过期|expired", text, re.IGNORECASE))
        has_nonexistent = bool(
            re.search(r"不存在|nonexistent|伪造|forged|无效|invalid", text, re.IGNORECASE)
        )
        return has_expired and has_nonexistent and bool(re.search(r"\b401\b", text))

    @staticmethod
    def _collapse_combined_auth_behaviors(values: list[str]) -> list[str]:
        candidate_indexes = [
            index
            for index, value in enumerate(values)
            if re.search(r"(?:过期|expired|不存在|nonexistent)", value, re.IGNORECASE)
            and re.search(r"(?:token|令牌|授权|会话)", value, re.IGNORECASE)
            and re.search(r"\b401\b", value)
        ]
        if not candidate_indexes:
            return [*values, "携带过期/不存在 Token 时返回 HTTP 401，通常无响应体。"]
        first = min(candidate_indexes)
        retained = [value for index, value in enumerate(values) if index not in candidate_indexes]
        retained.insert(first, "携带过期/不存在 Token 时返回 HTTP 401，通常无响应体。")
        return retained

    @staticmethod
    def _auth_negative_fixture_kind(point: TestPoint) -> str | None:
        if point.category != "negative":
            return None
        text = " ".join((point.title, point.action, point.expected_result)).casefold()
        if re.search(r"过期\s*/\s*不存在|expired\s*/\s*nonexistent", text):
            return "combined"
        if "$auth_fixture[nonexistent:token]" in text:
            return "nonexistent"
        if "$auth_fixture[expired:token]" in text:
            return "expired"
        if re.search(r"(?:过期|expired)[^\n。.!?]{0,40}(?:token|令牌|授权|会话)", text) or re.search(
            r"(?:token|令牌|授权|会话)[^\n。.!?]{0,40}(?:过期|expired)", text
        ):
            return "expired"
        if re.search(
            r"(?:不存在|nonexistent|伪造|forged|随机|random|无效|invalid)"
            r"[^\n。.!?]{0,40}(?:token|令牌|授权|会话)",
            text,
        ) or re.search(
            r"(?:token|令牌|授权|会话)[^\n。.!?]{0,40}"
            r"(?:不存在|nonexistent|伪造|forged|随机|random|无效|invalid)",
            text,
        ):
            return "nonexistent"
        return None

    @staticmethod
    def _merge_auth_negative_points(
        points: list[TestPoint],
        fixtures: dict[str, tuple[str, str]],
    ) -> list[TestPoint]:
        """Merge expired/nonexistent auth failures with the same HTTP outcome."""

        candidates = [
            point
            for point in points
            if ApiTestWorkflow._auth_negative_fixture_kind(point) in {"expired", "nonexistent"}
        ]
        if len(candidates) < 2:
            return points
        if not all(re.search(r"\b401\b", point.expected_result) for point in candidates):
            return points

        primary = candidates[0]
        fixture = fixtures.get("nonexistent") or fixtures.get("expired")
        evidence_refs = list(
            dict.fromkeys(
                reference
                for point in candidates
                for reference in point.evidence_refs
            )
        )
        action = primary.action
        if fixture:
            fixture_id, placeholder = fixture
            action = f"使用鉴权夹具 {placeholder} 请求当前接口。"
            evidence_refs.append(fixture_id)
        merged = primary.model_copy(
            update={
                "title": "过期/不存在 Token 返回 401",
                "action": action,
                "expected_result": "返回 HTTP 401。",
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
            }
        )
        candidate_ids = {point.point_id for point in candidates}
        retained = [point for point in points if point.point_id not in candidate_ids]
        retained.insert(min(points.index(point) for point in candidates), merged)
        return retained

    @staticmethod
    def _auth_fixture_evidence(
        evidence: EvidenceBundle | None,
    ) -> dict[str, tuple[str, str]]:
        fixtures: dict[str, tuple[str, str]] = {}
        if evidence is None:
            return fixtures
        for fact in evidence.facts:
            if fact.source_type.casefold() != "auth_fixture":
                continue
            kind = fact.metadata.get("fixture_kind")
            placeholder = fact.metadata.get("token_placeholder")
            if kind and placeholder:
                fixtures[kind] = (fact.evidence_id, placeholder)
        return fixtures

    @staticmethod
    def _normalize_test_points(
        points: TestPointCollection,
        requirement: RequirementDocument,
        state: WorkflowState | None = None,
    ) -> TestPointCollection:
        """Bind all NLU test points to the Requirement produced in this invocation."""

        known_evidence = (
            {fact.evidence_id for fact in state["evidence"].facts} if state else None
        )
        document_evidence = (
            [
                fact.evidence_id
                for fact in state["evidence"].facts
                if fact.source_type == "requirement_document"
            ]
            if state
            else []
        )

        normalized_points = []
        for point in points.points:
            evidence_refs = list(point.evidence_refs)
            if known_evidence is not None:
                evidence_refs = [ref for ref in evidence_refs if ref in known_evidence]
                if not evidence_refs and point.source == "requirement":
                    evidence_refs = document_evidence
            normalized_points.append(
                point.model_copy(
                    update={
                        "requirement_id": requirement.requirement_id,
                        "evidence_refs": list(dict.fromkeys(evidence_refs)),
                    }
                )
            )

        return points.model_copy(
            update={
                "requirement_id": requirement.requirement_id,
                "requirement_version": requirement.version,
                "points": normalized_points,
            }
        )

    @staticmethod
    def _requirement_explicitly_requires_strict_schema(requirement: RequirementDocument) -> bool:
        """Only retain response-schema assertions when strict fields are explicit.

        OpenAPI response schemas and phrases such as "common response structure"
        are not, by themselves, a business test requirement. Treating them as
        executable assertions lets a neighbouring operation's model output leak
        into the current API. A strict schema is retained only when the approved
        requirement explicitly constrains the complete field set.
        """

        text = "\n".join(
            [
                *requirement.preconditions,
                *requirement.business_rules,
                *requirement.expected_behaviors,
            ]
        ).casefold()
        markers = (
            "additionalproperties",
            "strict schema",
            "strict field",
            "exactly the following fields",
            "no additional fields",
            "不得出现额外字段",
            "不能有额外字段",
            "只能包含以下字段",
            "仅包含以下字段",
            "严格字段集合",
            "严格响应结构",
            "响应结构必须严格",
        )
        return any(marker.casefold() in text for marker in markers)

    @classmethod
    def _strip_unrequested_schema_assertions(
        cls,
        case_set: CaseSet,
        requirement: RequirementDocument,
    ) -> CaseSet:
        """Remove generic cross-operation schema checks from generated cases."""

        if cls._requirement_explicitly_requires_strict_schema(requirement):
            return case_set
        cases: list[TestCase] = []
        for case in case_set.cases:
            assertions = [
                assertion
                for assertion in case.assertions
                if assertion.type != "response_schema"
            ]
            if not assertions:
                # A contract-only case whose only purpose was a generic schema
                # check must not survive as an empty executable case.
                continue
            if len(assertions) != len(case.assertions):
                case = case.model_copy(update={"assertions": assertions})
            cases.append(case)
        return case_set.model_copy(update={"cases": cases})

    @classmethod
    def _complete_explicit_numeric_boundary_points(
        cls,
        points: TestPointCollection,
        requirement: RequirementDocument,
    ) -> TestPointCollection:
        """Deterministically preserve explicit numeric equivalence partitions.

        LLMs can occasionally collapse a documented exclusive lower bound into only
        its exact boundary value (for example, keeping ``0`` but omitting a negative
        representative for ``id > 0``). This narrow guard only acts when the
        normalized Requirement explicitly states both the exclusive lower bound and
        the failure behavior for values not greater than that bound.
        """

        rule_text = "\n".join(requirement.business_rules)
        completed = list(points.points)
        evidence_refs = [
            reference.evidence_id
            for reference in requirement.evidence_refs
            if reference.source_type == "requirement_document"
        ] or [reference.evidence_id for reference in requirement.evidence_refs]

        for parameter in requirement.api.parameters:
            threshold = cls._exclusive_lower_bound(parameter.name, rule_text)
            if threshold is None:
                continue
            failure_behavior = cls._not_greater_failure_behavior(
                parameter.name,
                threshold,
                requirement.expected_behaviors,
            )
            if failure_behavior is None:
                continue

            representatives = [
                ("AT-LOWER-BOUND", threshold, "等于下界"),
                ("BELOW-LOWER-BOUND", threshold - 1, "低于下界"),
            ]
            for partition, value, label in representatives:
                if cls._has_explicit_numeric_representative(
                    completed,
                    parameter.name,
                    value,
                ):
                    continue
                digest = sha256(
                    f"{requirement.requirement_id}:{parameter.name}:{partition}:{value}".encode()
                ).hexdigest()[:12].upper()
                completed.append(
                    TestPoint(
                        point_id=f"TP-AUTO-{digest}",
                        requirement_id=requirement.requirement_id,
                        title=f"{parameter.name} {label} {value} 时返回文档规定的失败结果",
                        category="boundary",
                        priority="high",
                        action=(
                            f"保留完整路径模板 {requirement.api.path}，"
                            f"令参数 {parameter.name}={value} 发送一次请求。"
                        ),
                        expected_result=failure_behavior,
                        evidence_refs=evidence_refs,
                        parameter_refs=[parameter.name],
                        source="requirement",
                    )
                )

        return points.model_copy(update={"points": completed})

    def _resolve_exact_numeric_boundary_fixtures(
        self,
        requirement: RequirementDocument,
        points: TestPointCollection,
        state: WorkflowState,
    ) -> tuple[RequirementDocument, TestPointCollection]:
        """Resolve an inferred exact valid boundary against the configured database."""

        project = self.project_service.get(state["project_id"])
        evidence_by_id = {fact.evidence_id: fact for fact in state["evidence"].facts}
        referenced_ids = {reference.evidence_id for reference in requirement.evidence_refs}
        fixture_facts = [
            evidence_by_id[evidence_id]
            for evidence_id in referenced_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].source_type == "database_fixture"
        ]
        completed = list(points.points)
        expected_behaviors = list(requirement.expected_behaviors)
        unresolved_questions = list(requirement.unresolved_questions)
        rule_text = "\n".join(requirement.business_rules)
        resolver = DatabaseFixtureResolver()

        for parameter in requirement.api.parameters:
            threshold = self._exclusive_lower_bound(parameter.name, rule_text)
            if threshold is None:
                continue
            exact_value = threshold + 1
            ambiguous = [
                point
                for point in completed
                if self._is_ambiguous_exact_boundary_point(
                    point,
                    parameter.name,
                    exact_value,
                )
            ]
            for point in ambiguous:
                fixture_fact = next(
                    (
                        fact
                        for fact in fixture_facts
                        if f":{parameter.name}]" in fact.fact
                        and fact.metadata.get("table")
                    ),
                    None,
                )
                if not project.settings.database.enabled or fixture_fact is None:
                    completed.remove(point)
                    unresolved_questions.append(
                        f"{point.title} 需要读取允许表确认精确值 {parameter.name}={exact_value} "
                        "是否存在；当前没有可用的本地只读数据库夹具。"
                    )
                    continue
                table_name = str(fixture_fact.metadata["table"])
                try:
                    fixture_kind = resolver.classify_exact_value(
                        project.settings,
                        table_name=table_name,
                        column_name=parameter.name,
                        value=exact_value,
                    )
                except Exception as exc:
                    completed.remove(point)
                    unresolved_questions.append(
                        f"{point.title} 的精确数据库夹具读取失败：{type(exc).__name__}。"
                    )
                    continue

                counterpart_kind = "existing" if fixture_kind == "present" else "absent"
                counterpart_token = (
                    f"$DB_FIXTURE[{counterpart_kind}:{table_name}:{parameter.name}]"
                )
                counterpart = next(
                    (
                        candidate
                        for candidate in completed
                        if candidate is not point and counterpart_token in candidate.action
                    ),
                    None,
                )
                expected_result = (
                    counterpart.expected_result if counterpart is not None else point.expected_result
                )
                exact_token = (
                    f"$DB_FIXTURE[{fixture_kind}:{table_name}:{parameter.name}:{exact_value}]"
                )
                replacement = point.model_copy(
                    update={
                        "title": (
                            f"{point.title}（数据库已确认"
                            f"{'存在' if fixture_kind == 'present' else '不存在'}）"
                        ),
                        "action": (
                            f"使用本地精确夹具令牌 {exact_token} 作为参数 "
                            f"{parameter.name}，发送当前 Operation 请求。"
                        ),
                        "expected_result": expected_result,
                        "evidence_refs": list(
                            dict.fromkeys([*point.evidence_refs, fixture_fact.evidence_id])
                        ),
                    }
                )
                completed[completed.index(point)] = replacement
                expected_behaviors = [
                    behavior
                    for behavior in expected_behaviors
                    if not self._is_ambiguous_exact_boundary_text(
                        behavior,
                        parameter.name,
                        exact_value,
                    )
                ]
                expected_behaviors.append(
                    f"{parameter.name}={exact_value} 已由本地只读数据库确认"
                    f"{'存在' if fixture_kind == 'present' else '不存在'}；{expected_result}"
                )

        return (
            requirement.model_copy(
                update={
                    "expected_behaviors": list(dict.fromkeys(expected_behaviors)),
                    "unresolved_questions": list(dict.fromkeys(unresolved_questions)),
                }
            ),
            points.model_copy(update={"points": completed}),
        )

    @classmethod
    def _is_ambiguous_exact_boundary_point(
        cls,
        point: TestPoint,
        parameter_name: str,
        exact_value: int,
    ) -> bool:
        if point.category != "boundary" or "$DB_FIXTURE[" in point.action:
            return False
        if not cls._has_explicit_numeric_representative(
            [point],
            parameter_name,
            exact_value,
        ):
            return False
        return cls._has_ambiguous_business_branches(point.expected_result)

    @staticmethod
    def _is_ambiguous_exact_boundary_text(
        text: str,
        parameter_name: str,
        exact_value: int,
    ) -> bool:
        if not re.search(rf"\b{re.escape(parameter_name)}\b", text, flags=re.IGNORECASE):
            return False
        if not re.search(rf"(?<!\d){re.escape(str(exact_value))}(?!\d)", text):
            return False
        return ApiTestWorkflow._has_ambiguous_business_branches(text)

    @staticmethod
    def _has_ambiguous_business_branches(text: str) -> bool:
        folded = text.casefold()
        has_both_boolean_branches = (
            "success" in folded
            and re.search(r"(?:为|=|is)\s*true", folded) is not None
            and re.search(r"(?:为|=|is)\s*false", folded) is not None
        )
        has_conditional_alternatives = folded.count("若") >= 2 or folded.count("if ") >= 2
        return has_both_boolean_branches or has_conditional_alternatives

    @staticmethod
    def _exclusive_lower_bound(parameter_name: str, text: str) -> int | None:
        name = re.escape(parameter_name)
        patterns = (
            rf"(?:参数\s*)?{name}\b[^\n。.]*?大于\s*(-?\d+)",
            rf"\b{name}\b[^\n.]*?(?:must\s+be\s+)?greater\s+than\s+(-?\d+)",
            rf"\b{name}\b[^\n.]*?>\s*(-?\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _not_greater_failure_behavior(
        parameter_name: str,
        threshold: int,
        expected_behaviors: list[str],
    ) -> str | None:
        name = re.escape(parameter_name)
        boundary = re.escape(str(threshold))
        patterns = (
            rf"不大于\s*{boundary}",
            rf"(?:<=|≤)\s*{boundary}",
            rf"(?:less\s+than\s+or\s+equal\s+to|not\s+greater\s+than)\s+{boundary}",
        )
        for behavior in expected_behaviors:
            if not re.search(rf"\b{name}\b", behavior, flags=re.IGNORECASE):
                continue
            if any(re.search(pattern, behavior, flags=re.IGNORECASE) for pattern in patterns):
                return behavior
        return None

    @staticmethod
    def _has_explicit_numeric_representative(
        points: list[TestPoint],
        parameter_name: str,
        value: int,
    ) -> bool:
        value_pattern = rf"(?<!\d){re.escape(str(value))}(?!\d)"
        parameter_pattern = rf"\b{re.escape(parameter_name)}\b"
        for point in points:
            text = " ".join((point.title, point.action, point.expected_result))
            if re.search(parameter_pattern, text, flags=re.IGNORECASE) and re.search(
                value_pattern,
                text,
            ):
                return True
        return False

    @classmethod
    def _merge_cross_cutting_contract_cases(cls, cases: list[TestCase]) -> list[TestCase]:
        """Fold a same-request contract check into its business scenario.

        A response envelope/schema is an assertion dimension. When a contract Case
        sends exactly the same request as a positive, negative, or boundary Case, a
        second HTTP execution adds no scenario coverage and makes reports misleading.
        """

        merged = [case for case in cases if case.category != "contract"]
        contract_cases = [case for case in cases if case.category == "contract"]
        for contract in contract_cases:
            request_key = cls._request_merge_key(contract)
            target_index = next(
                (
                    index
                    for index, candidate in enumerate(merged)
                    if cls._request_merge_key(candidate) == request_key
                ),
                None,
            )
            if target_index is None:
                merged.append(contract)
                continue
            target = merged[target_index]
            assertion_keys = {
                cls._assertion_semantic_key(assertion) for assertion in target.assertions
            }
            assertions = list(target.assertions)
            for assertion in contract.assertions:
                key = cls._assertion_semantic_key(assertion)
                if key not in assertion_keys:
                    assertion_keys.add(key)
                    assertions.append(assertion)
            merged[target_index] = target.model_copy(
                update={
                    "test_point_ids": list(
                        dict.fromkeys([*target.test_point_ids, *contract.test_point_ids])
                    ),
                    "assertions": assertions,
                    "evidence_refs": list(
                        dict.fromkeys([*target.evidence_refs, *contract.evidence_refs])
                    ),
                }
            )
        return merged

    @staticmethod
    def _request_merge_key(case: TestCase) -> str:
        request = case.request

        def normalize(values: dict[str, Any]) -> dict[str, Any]:
            return {
                str(key).casefold(): str(value) if value is not None else None
                for key, value in values.items()
            }

        value = {
            "method": request.method.upper(),
            "path": request.path,
            "path_params": normalize(request.path_params),
            "query_params": normalize(request.query_params),
            "headers": normalize(request.headers),
            "body": request.body,
        }
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _assertion_semantic_key(assertion) -> str:
        value = {
            "type": assertion.type,
            "path": assertion.path,
            "expected": assertion.expected,
            "operator": assertion.operator,
        }
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _require_requirement(requirement: RequirementDocument, state: WorkflowState) -> None:
        if requirement.api.operation_id != state["operation"].operation_id:
            raise ValueError("requirement API operation_id does not match selected operation")
        known_evidence = {fact.evidence_id for fact in state["evidence"].facts}
        unknown_refs = {item.evidence_id for item in requirement.evidence_refs} - known_evidence
        if unknown_refs:
            raise ValueError(f"requirement referenced unknown evidence: {sorted(unknown_refs)}")

    @staticmethod
    def _normalize_case_evidence(case_set: CaseSet, state: WorkflowState) -> CaseSet:
        """Fill omitted case/assertion evidence from the linked Test Points.

        Evidence references remain deterministic and are never invented. This is a
        boundary normalization for LLM output: when the model put the evidence on
        the Case but omitted it on an Assertion (or omitted both while linking a
        Test Point), the assertion inherits the known references before strict
        validation runs.
        """

        return case_set.model_copy(
            update={"cases": ApiTestWorkflow._normalize_case_list(case_set.cases, state)}
        )

    @staticmethod
    def _normalize_case_list(cases: list[TestCase], state: WorkflowState) -> list[TestCase]:
        known_evidence = {fact.evidence_id for fact in state["evidence"].facts}
        points_by_id = {point.point_id: point for point in state["test_points"].points}
        normalized: list[TestCase] = []
        for case in cases:
            case_evidence_refs = list(
                dict.fromkeys(ref for ref in case.evidence_refs if ref in known_evidence)
            )
            if not case_evidence_refs:
                inherited_refs: list[str] = []
                for point_id in case.test_point_ids:
                    point = points_by_id.get(point_id)
                    if point:
                        inherited_refs.extend(
                            ref for ref in point.evidence_refs if ref in known_evidence
                        )
                case_evidence_refs = list(dict.fromkeys(inherited_refs))

            assertions = []
            for assertion in case.assertions:
                assertion_evidence_refs = list(
                    dict.fromkeys(
                        ref for ref in assertion.evidence_refs if ref in known_evidence
                    )
                )
                if not assertion_evidence_refs:
                    assertion_evidence_refs = case_evidence_refs
                assertions.append(
                    assertion.model_copy(update={"evidence_refs": assertion_evidence_refs})
                )
            request = case.request
            path_params = dict(request.path_params)
            query_params = dict(request.query_params)
            for point_id in case.test_point_ids:
                point = points_by_id.get(point_id)
                if point is None:
                    continue
                for match in _EXACT_FIXTURE_IN_TEXT.finditer(point.action):
                    token = match.group(0)
                    column_name = match.group(3)
                    raw_value = match.group(4)
                    if column_name in path_params and str(path_params[column_name]) == raw_value:
                        path_params[column_name] = token
                    if column_name in query_params and str(query_params[column_name]) == raw_value:
                        query_params[column_name] = token
            request = request.model_copy(
                update={"path_params": path_params, "query_params": query_params}
            )
            normalized.append(
                case.model_copy(
                    update={
                        "evidence_refs": case_evidence_refs,
                        "assertions": assertions,
                        "request": request,
                    }
                )
            )
        return normalized

    @staticmethod
    def _validate_cases(cases: list[TestCase], state: WorkflowState, *, source: str) -> None:
        requirement = state["requirement"]
        expected_source = source
        known_points = {point.point_id for point in state["test_points"].points}
        known_evidence = {fact.evidence_id for fact in state["evidence"].facts}
        errors: list[str] = []
        for case in cases:
            if case.requirement_id != requirement.requirement_id:
                errors.append(f"case {case.case_id} has mismatched requirement_id")
            if case.source != expected_source:
                errors.append(f"case {case.case_id} must have source={expected_source}")
            errors.extend(
                f"{case.case_id}: {error}"
                for error in validate_case(
                    case,
                    known_test_points=known_points,
                    known_evidence=known_evidence,
                    operation=state["operation"],
                )
            )
        if errors:
            raise ValueError("invalid workflow cases: " + "; ".join(errors))

    @staticmethod
    def _partition_valid_cases(
        cases: list[TestCase], state: WorkflowState, *, source: str
    ) -> tuple[list[TestCase], list[str]]:
        """Keep model mistakes from failing the whole workflow.

        Invalid cases remain visible as deterministic review gaps. Valid cases
        continue through Reviewer and final assembly, where missing Test Point
        coverage becomes NEEDS_CLARIFICATION instead of an opaque workflow error.
        """

        valid_cases: list[TestCase] = []
        notes: list[str] = []
        for case in cases:
            try:
                ApiTestWorkflow._validate_cases([case], state, source=source)
            except ValueError as exc:
                notes.append(f"Discarded invalid {source} case {case.case_id}: {exc}")
            else:
                valid_cases.append(case)
        return valid_cases, notes

    @staticmethod
    def _validate_review_output(output: ReviewerAgentOutput, state: WorkflowState) -> None:
        known_points = {point.point_id for point in state["test_points"].points}
        known_evidence = {fact.evidence_id for fact in state["evidence"].facts}
        referenced_points = set(output.missing_test_point_ids)
        referenced_points.update(
            point_id
            for spec in output.suggested_case_specs
            for point_id in spec.target_test_point_ids
        )
        unknown_points = referenced_points - known_points
        if unknown_points:
            raise ValueError(f"reviewer referenced unknown test points: {sorted(unknown_points)}")
        unknown_evidence = {
            evidence_id
            for spec in output.suggested_case_specs
            for evidence_id in spec.evidence_refs
            if evidence_id not in known_evidence
        }
        if unknown_evidence:
            raise ValueError(f"reviewer referenced unknown evidence: {sorted(unknown_evidence)}")
        spec_ids = [spec.spec_id for spec in output.suggested_case_specs]
        if len(set(spec_ids)) != len(spec_ids):
            raise ValueError("reviewer returned duplicate suggested case spec IDs")

    @staticmethod
    def _case_semantic_key(case: TestCase) -> str:
        value = {
            "test_point_ids": sorted(case.test_point_ids),
            "request": case.request.model_dump(mode="json"),
            "assertions": [
                {
                    "type": assertion.type,
                    "path": assertion.path,
                    "expected": assertion.expected,
                    "operator": assertion.operator,
                }
                for assertion in case.assertions
            ],
        }
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _update(
        state: WorkflowState,
        *,
        status: str | None = None,
        node: str = "workflow",
        message: str,
        **values: Any,
    ) -> dict[str, Any]:
        event: WorkflowEvent = {
            "node": node,
            "status": status or state.get("status", "RUNNING"),
            "message": message,
        }
        return {
            **values,
            **({"status": status} if status else {}),
            "events": [*state.get("events", []), event],
        }
