from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.models.auth import AuthProtocol
from app.models.contracts import OperationContract
from app.models.evidence import EvidenceBundle, EvidenceFact


_PREFIX_NAMES = ("Bearer", "Basic", "JWT", "Token", "Digest", "DPoP")
_PREFIX_PATTERN = "(?:" + "|".join(_PREFIX_NAMES) + ")"
_NO_PREFIX_RE = re.compile(
    rf"(?ix)"
    rf"(?:不使用|不带|不加|无需|不要|不需要|without|no)\s*[`\"']?{_PREFIX_PATTERN}"
    rf"\s*(?:前缀|prefix)?"
    rf"|(?:without|no)\s+(?:a\s+)?(?:token\s+)?prefix"
    rf"|(?:token|令牌)\s*(?:直接|原样)\s*(?:放入|写入|携带|发送)"
    rf"|(?:直接放入|直接写入|directly\s+(?:put|place|send))"
    rf"[^\n。.;；]{{0,80}}(?:authorization|请求头|header)"
)
_POSITIVE_PREFIX_RE = re.compile(
    rf"(?ix)"
    rf"(?:authorization|请求头|header)\s*[:：=]?\s*[`\"']?"
    rf"(?P<prefix>{_PREFIX_PATTERN})\b"
    rf"|(?P<prefix_after>{_PREFIX_PATTERN})\s+(?:<[^>]+>|token|令牌)"
    rf"|(?:使用|带|添加|加上|采用|with|use)\s*[`\"']?"
    rf"(?P<prefix_word>{_PREFIX_PATTERN})\s*(?:前缀|prefix)"
)
_HEADER_RE = re.compile(
    r"(?ix)(?:请求头|header)\s*[:：=]?\s*[`\"']?(?P<header>[A-Za-z][A-Za-z0-9_-]{1,199})"
)
_AUTH_CONTEXT_RE = re.compile(
    r"(?ix)(?:authorization|认证|鉴权|token|令牌|Bearer|Basic|JWT|请求头|header)"
)


@dataclass(frozen=True)
class _AuthSignal:
    prefix: str | None
    explicit: bool
    conflict: bool
    header_name: str


def extract_auth_protocol(
    *,
    operation: OperationContract,
    document_excerpt: str | None,
    evidence: EvidenceBundle | None,
) -> AuthProtocol:
    """Infer the selected operation's auth wire format from ranked evidence.

    Requirement-document text for the selected operation is highest priority.
    Lower-priority contract/source evidence is used only when the requirement
    document does not state a protocol.  No prefix is inferred from silence.
    """

    candidates: list[tuple[int, str, str, list[str]]] = []
    if document_excerpt:
        requirement_ids = [
            fact.evidence_id
            for fact in (evidence.facts if evidence else [])
            if fact.source_type == "requirement_document"
        ]
        candidates.append((0, "requirement_document", document_excerpt, requirement_ids))

    metadata = operation.contract_metadata or {}
    if metadata:
        metadata_text = json.dumps(metadata, ensure_ascii=False, default=str)
        candidates.append((1, "operation_contract", metadata_text, []))

    for fact in (evidence.facts if evidence else []):
        if fact.source_type == "requirement_document":
            continue
        text = fact.safe_excerpt or fact.fact
        if text:
            rank = {
                "operation_yaml": 1,
                "openapi": 1,
                "source_code": 2,
            }.get(fact.source_type, 3)
            candidates.append((rank, fact.source_type, text, [fact.evidence_id]))

    candidates.sort(key=lambda item: item[0])
    for rank in sorted({item[0] for item in candidates}):
        ranked = [item for item in candidates if item[0] == rank]
        signals = [(_signal(text), source, ids) for _, source, text, ids in ranked]
        explicit = [item for item in signals if item[0].explicit]
        if not explicit:
            continue

        prefixes = {signal.prefix for signal, _, _ in explicit}
        header_names = {signal.header_name for signal, _, _ in explicit}
        has_conflict = len(prefixes) > 1 or any(signal.conflict for signal, _, _ in explicit)
        evidence_ids = [evidence_id for _, _, ids in explicit for evidence_id in ids]
        sources = [source for _, source, _ in explicit]
        header_name = next(iter(header_names), "Authorization")
        if has_conflict:
            return AuthProtocol(
                header_name=header_name,
                status="conflict",
                evidence_ids=list(dict.fromkeys(evidence_ids)),
                source=", ".join(dict.fromkeys(sources)),
                conflicts=[
                    "当前鉴权证据同时声明了不同的 Token 前缀，不能自动选择。"
                ],
            )

        selected = next(iter(prefixes))
        lower_conflicts = [
            source
            for lower_rank, source, text, _ in candidates
            if lower_rank > rank and _signal(text).explicit and _signal(text).prefix != selected
        ]
        conflicts = (
            [f"低优先级证据 {source} 声明了不同的 Token 前缀，已按当前接口需求文档优先。"
             for source in dict.fromkeys(lower_conflicts)]
        )
        return AuthProtocol(
            header_name=header_name,
            prefix=selected,
            status="explicit",
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            source=", ".join(dict.fromkeys(sources)),
            conflicts=conflicts,
        )

    return AuthProtocol()


def normalize_auth_text(text: str, protocol: AuthProtocol) -> tuple[str, bool]:
    """Remove unsupported model-invented auth syntax for one operation.

    This only rewrites phrases in an authentication context.  It does not
    alter arbitrary business text mentioning the word Bearer.
    """

    if not text or not _AUTH_CONTEXT_RE.search(text):
        return text, False
    if protocol.status == "explicit" and protocol.prefix is None:
        updated = text
        updated = re.sub(r"(?i)(携带|使用|添加|加上)\s*Bearer\s*前缀", r"\1Token", updated)
        updated = re.sub(r"(?i)Bearer\s+前缀", "无前缀", updated)
        updated = re.sub(r"(?i)Bearer\s+(?=(?:token|令牌|<token>))", "", updated)
        updated = re.sub(r"(?i)\bBearer\s+prefix\b", "no prefix", updated)
        updated = re.sub(r"(?i)\b无\s+无前缀\b", "无前缀", updated)
        updated = re.sub(r"(?i)\bno\s+no\s+prefix\b", "no prefix", updated)
        updated = re.sub(r"(?i)\s{2,}", " ", updated).strip()
        return updated, updated != text

    if protocol.status in {"unknown", "conflict"}:
        if re.search(r"(?i)\bBearer\b", text):
            updated = re.sub(r"(?i)(?:携带|使用|添加|加上)?\s*Bearer\s*前缀", "使用项目配置的认证凭据", text)
            updated = re.sub(r"(?i)Bearer\s+(?=(?:token|令牌|<token>))", "项目配置的认证凭据 ", updated)
            updated = re.sub(r"(?i)\bwith\s+Bearer\s+prefix\b", "with the project auth credential", updated)
            updated = re.sub(r"(?i)\s{2,}", " ", updated).strip()
            return updated, updated != text

    return text, False


def _signal(text: str) -> _AuthSignal:
    header_name = "Authorization"
    header_match = _HEADER_RE.search(text)
    if header_match:
        header_name = header_match.group("header")

    no_prefix = list(_NO_PREFIX_RE.finditer(text))
    masked = list(text)
    for match in no_prefix:
        for index in range(match.start(), match.end()):
            masked[index] = " "
    positive = list(_POSITIVE_PREFIX_RE.finditer("".join(masked)))
    prefixes: set[str] = set()
    for match in positive:
        value = match.group("prefix") or match.group("prefix_after") or match.group("prefix_word")
        if value:
            prefixes.add(value.capitalize())

    no_prefix_detected = bool(no_prefix)
    conflict = no_prefix_detected and bool(prefixes)
    if conflict or len(prefixes) > 1:
        return _AuthSignal(prefix=None, explicit=True, conflict=True, header_name=header_name)
    if no_prefix_detected:
        return _AuthSignal(prefix=None, explicit=True, conflict=False, header_name=header_name)
    if prefixes:
        return _AuthSignal(prefix=next(iter(prefixes)), explicit=True, conflict=False, header_name=header_name)
    return _AuthSignal(prefix=None, explicit=False, conflict=False, header_name=header_name)
