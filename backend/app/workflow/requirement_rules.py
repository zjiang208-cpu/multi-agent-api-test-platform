from __future__ import annotations

import re

from app.models.cases import CaseSet, TestCase
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection
from app.workflow.state import WorkflowState


class RequirementRulesMixin:
    """Requirement-source selection and NLU output normalization rules."""

    @staticmethod
    def _operation_requirement_excerpt(operation, document: str) -> str:
        """Return the current operation document section without dropping sibling rules.

        Discovery source ranges often point at the operation's basic-info table only.
        For markdown documents that group parameters, response rules, and failure
        scenarios under one top-level API heading, returning that narrow range loses
        observable response requirements before NLU sees them.
        """

        lines = document.splitlines()
        line_count = len(lines)

        def heading_level(line: str) -> int | None:
            match = re.match(r"^\s*(#+)\s+", line)
            return len(match.group(1)) if match else None

        def document_section_excerpt(anchor_index: int) -> str:
            top_start = 0
            for candidate in range(anchor_index, -1, -1):
                if heading_level(lines[candidate]) == 1:
                    top_start = candidate
                    break
            top_end = line_count
            for candidate in range(top_start + 1, line_count):
                if heading_level(lines[candidate]) == 1:
                    top_end = candidate
                    break

            # A generic top-level heading may contain several operations. In
            # that case isolate the nearest operation subsection; otherwise a
            # top-level heading such as "Get item" owns all of its child rules.
            top_title = lines[top_start].lstrip("#").strip().casefold()
            generic_top_level = any(
                marker in top_title
                for marker in ("api", "rule", "接口", "需求", "文档", "document")
            )
            path_hits = [
                candidate
                for candidate in range(top_start, top_end)
                if re.search(re.escape(operation.path), lines[candidate], re.IGNORECASE)
            ]
            if len(path_hits) <= 1 and not generic_top_level:
                return "\n".join(lines[top_start:top_end]).strip()[:9_000]

            selected_anchor = min(
                path_hits or [anchor_index],
                key=lambda candidate: abs(candidate - anchor_index),
            )
            start = top_start
            section_level = 1
            for candidate in range(selected_anchor, top_start - 1, -1):
                level = heading_level(lines[candidate])
                if level is not None and level > 1:
                    start = candidate
                    section_level = level
                    break
            end = top_end
            for candidate in range(start + 1, top_end):
                level = heading_level(lines[candidate])
                if level is not None and level <= section_level:
                    end = candidate
                    break
            return "\n".join(lines[start:end]).strip()[:9_000]

        for source in operation.source_refs:
            if source.source_document_id and source.source_document_id != operation.source_document_id:
                continue
            start = source.start_line or 0
            end = source.end_line or 0
            reference = source.reference or ""
            has_specific_range = ":lines:" in reference or start > 1 or end < line_count
            if has_specific_range and 1 <= start <= end <= line_count:
                return document_section_excerpt(start - 1)

        method = re.escape(operation.method)
        path = re.escape(operation.path)
        path_pattern = rf"{path}(?![A-Za-z0-9_/{{])"
        exact_line = re.compile(rf"(?i)\b{method}\b.*{path_pattern}|{path_pattern}.*\b{method}\b")

        for index, line in enumerate(lines):
            if exact_line.search(line):
                return document_section_excerpt(index)

        path_only = re.compile(path_pattern, re.IGNORECASE)
        for index, line in enumerate(lines):
            if path_only.search(line):
                return document_section_excerpt(index)

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
        """Add document-level auth protocol rules to the selected operation excerpt."""

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

    @staticmethod
    def _normalize_requirement(requirement: RequirementDocument, state: WorkflowState) -> RequirementDocument:
        """Bind the selected Operation and source document as deterministic anchors."""

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
        """Only retain response-schema assertions when strict fields are explicit."""

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
