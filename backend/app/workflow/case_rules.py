from __future__ import annotations

import json
import re
from typing import Any

from app.cases.validator import validate_case
from app.models.cases import CaseSet, TestCase
from app.models.requirements import RequirementDocument
from app.workflow.models import ReviewerAgentOutput
from app.workflow.state import WorkflowEvent, WorkflowState


_EXACT_FIXTURE_IN_TEXT = re.compile(
    r"\$DB_FIXTURE\[(present|missing):([A-Za-z0-9_]+):([A-Za-z0-9_]+):(-?\d+)\]"
)


class CaseRulesMixin:
    """Case merging, normalization, and validation rules."""
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
            update={"cases": CaseRulesMixin._normalize_case_list(case_set.cases, state)}
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
                CaseRulesMixin._validate_cases([case], state, source=source)
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

