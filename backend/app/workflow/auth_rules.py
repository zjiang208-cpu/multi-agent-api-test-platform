from __future__ import annotations

import re
from typing import Any

from app.models.auth import AuthProtocol
from app.models.cases import CaseSet, TestCase
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument, RequirementEvidenceRef
from app.models.testpoints import TestPoint, TestPointCollection
from app.workflow.auth_protocol import normalize_auth_text
from app.workflow.state import WorkflowState


_AUTH_PLACEHOLDER_MARKERS = ("<redacted>", "<token>", "${token}", "$TOKEN", "YOUR_TOKEN")


class AuthRulesMixin:
    """Authentication-specific normalization and fixture binding rules."""

    @staticmethod
    def _has_unresolved_authentication(case: TestCase, project_settings) -> bool:
        """Detect model-redacted credentials without treating the case as invalid."""

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
        """Replace model-redacted negative credentials with safe local fixtures."""

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

    @classmethod
    def _normalize_auth_protocol_output(
        cls,
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
        fixture_by_kind = cls._auth_fixture_evidence(evidence)
        normalized_points = cls._merge_auth_negative_points(
            normalized_points,
            fixture_by_kind,
        )
        combined_auth_semantics = cls._has_combined_auth_semantics(requirement_updates)
        if combined_auth_semantics:
            requirement_updates["expected_behaviors"] = cls._collapse_combined_auth_behaviors(
                requirement_updates["expected_behaviors"]
            )
            normalized_points = [
                (
                    point.model_copy(
                        update={
                            "title": "过期/不存在 Token 返回 401",
                            "expected_result": "返回 HTTP 401，通常无响应体。",
                        }
                    )
                    if cls._auth_negative_fixture_kind(point)
                    in {"expired", "nonexistent", "combined"}
                    and re.search(r"\b401\b", point.expected_result)
                    else point
                )
                for point in normalized_points
            ]
        requirement_evidence_refs = list(requirement.evidence_refs)
        for index, point in enumerate(normalized_points):
            fixture_kind = cls._auth_negative_fixture_kind(point)
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

    @classmethod
    def _merge_auth_negative_points(
        cls,
        points: list[TestPoint],
        fixtures: dict[str, tuple[str, str]],
    ) -> list[TestPoint]:
        """Merge expired/nonexistent auth failures with the same HTTP outcome."""

        candidates = [
            point
            for point in points
            if cls._auth_negative_fixture_kind(point) in {"expired", "nonexistent"}
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
