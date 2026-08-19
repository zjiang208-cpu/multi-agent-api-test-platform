from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from app.cases.validator import validate_case
from app.evidence.providers.database import DatabaseFixtureResolver
from app.models.cases import CaseSet, TestCase
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPoint, TestPointCollection
from app.workflow.agents import StructuredLangChainAgent
from app.workflow.auth_rules import AuthRulesMixin
from app.workflow.models import ReviewerAgentOutput
from app.workflow.requirement_rules import RequirementRulesMixin
from app.workflow.state import WorkflowEvent, WorkflowState


_EXACT_FIXTURE_IN_TEXT = re.compile(
    r"\$DB_FIXTURE\[(present|missing):([A-Za-z0-9_]+):([A-Za-z0-9_]+):(-?\d+)\]"
)


class WorkflowRulesMixin(AuthRulesMixin, RequirementRulesMixin):
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
        return WorkflowRulesMixin._has_ambiguous_business_branches(text)

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
            update={"cases": WorkflowRulesMixin._normalize_case_list(case_set.cases, state)}
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
                WorkflowRulesMixin._validate_cases([case], state, source=source)
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
