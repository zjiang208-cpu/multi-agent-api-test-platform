from __future__ import annotations

import re
from typing import Any

from app.models.cases import CaseSet, TestCase
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.workflow.agents import StructuredLangChainAgent
from app.workflow.auth_rules import AuthRulesMixin
from app.workflow.boundary_rules import BoundaryRulesMixin
from app.workflow.case_rules import CaseRulesMixin
from app.workflow.requirement_rules import RequirementRulesMixin
from app.workflow.state import WorkflowState


class WorkflowRulesMixin(AuthRulesMixin, RequirementRulesMixin, CaseRulesMixin, BoundaryRulesMixin):
    """Pure workflow normalization, validation, and case assembly rules."""

    # Evidence selection, authentication normalization, and model-output safety.

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

    # Requirement, boundary, Case, and Reviewer validation rules.

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
