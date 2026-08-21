from __future__ import annotations

import json
import re
from typing import Iterable

from app.models.cases import Assertion, TestCase
from app.models.testpoints import TestPoint


_STATUS_RE = re.compile(r"HTTP(?:\s*状态码)?\s*(?:为|=|:|：|\s)+\s*(?P<value>[1-5]\d{2})", re.IGNORECASE)
_SUCCESS_RE = re.compile(
    r"success(?:\s*字段)?\s*(?:为|是|=|:|：)\s*(?P<value>true|false)",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(
    r"errorMsg\s*(?:为|是|=|:|：)\s*[`'\"“‘]?(?P<value>[^`'\"”’\r\n，。;；]+)",
    re.IGNORECASE,
)
_DATA_TYPE_RE = re.compile(
    r"data(?:\s*字段)?\s*(?:为|是)\s*(?:非空)?\s*(?P<value>数组|列表|对象)",
    re.IGNORECASE,
)
_EMPTY_ARRAY_RE = re.compile(
    r"(?:空数组|空列表|数组为空|列表为空|无数据[^。；;\n]{0,30}(?:空数组|空列表))",
    re.IGNORECASE,
)
_FIELD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_FIELD_ALIASES = {
    "创建时间": "createTime",
    "更新时间": "updateTime",
    "手机号": "phone",
    "密码": "password",
}


def enrich_case_assertions(case: TestCase, points: Iterable[TestPoint]) -> TestCase:
    """补齐需求文本中明确写出的基本响应断言。

    这是通用的边界归一化，不读取接口名称，也不为某个接口写固定规则。
    LLM 已生成的断言优先保留；只有同一测试点的 expected_result 明确出现的
    状态码、success、errorMsg 和响应形态才会被补入。
    """

    points = list(points)
    texts = [
        text
        for point in points
        for text in (point.title, point.action, point.expected_result)
        if text
    ]
    if not texts:
        return case
    evidence_refs = list(
        dict.fromkeys(
            ref
            for point in points
            for ref in point.evidence_refs
            if ref
        )
    ) or list(case.evidence_refs)
    combined_text = "；".join(texts)
    declared_fields = set(_fields_after_keywords(combined_text, include=True))
    declared_fields.update(_fields_after_keywords(combined_text, include=False))
    absent_fields = set(_fields_after_keywords(combined_text, include=False))
    assertions = _normalize_existing_assertions(
        case.assertions,
        declared_fields=declared_fields,
        absent_fields=absent_fields,
    )
    absent_path_prefix = _absent_field_path_prefix(assertions, absent_fields)
    signatures = {_assertion_signature(item) for item in assertions}
    suffix = 1

    def add(
        assertion_type: str,
        *,
        path: str | None = None,
        expected=None,
        operator: str | None = None,
        label: str,
    ) -> None:
        nonlocal suffix
        candidate = Assertion(
            assertion_id=f"{case.case_id}-BASIC-{label}",
            type=assertion_type,
            path=path,
            expected=expected,
            operator=operator,
            evidence_refs=evidence_refs,
        )
        signature = _assertion_signature(candidate)
        if signature in signatures:
            return
        while candidate.assertion_id in {item.assertion_id for item in assertions}:
            suffix += 1
            candidate = candidate.model_copy(
                update={"assertion_id": f"{case.case_id}-BASIC-{label}-{suffix}"}
            )
        assertions.append(candidate)
        signatures.add(signature)

    for value in dict.fromkeys(int(match.group("value")) for match in _STATUS_RE.finditer(combined_text)):
        add("status_code", expected=value, operator="eq", label=f"STATUS-{value}")
    for match in _SUCCESS_RE.finditer(combined_text):
        value = match.group("value").casefold() == "true"
        add("json_value", path="$.success", expected=value, label=f"SUCCESS-{str(value).lower()}")
    for match in _ERROR_RE.finditer(combined_text):
        value = match.group("value").strip()
        if value:
            add("json_value", path="$.errorMsg", expected=value, label="ERRORMSG")
    for match in _DATA_TYPE_RE.finditer(combined_text):
        expected = "array" if match.group("value") in {"数组", "列表"} else "object"
        add("json_type", path="$.data", expected=expected, label=f"DATA-{expected.upper()}")

    if _EMPTY_ARRAY_RE.search(combined_text):
        add("json_type", path="$.data", expected="array", label="DATA-EMPTY-ARRAY")
        add(
            "json_value",
            path="$.data.length",
            expected=0,
            operator="eq",
            label="DATA-EMPTY-LENGTH",
        )

    for field in _fields_after_keywords(combined_text, include=True):
        path = f"$.data.{field}"
        add("json_exists", path=path, expected=True, label=f"EXISTS-{field.upper()}")
    for field in _fields_after_keywords(combined_text, include=False):
        path = f"{absent_path_prefix}{field}"
        add("json_exists", path=path, expected=False, label=f"ABSENT-{field.upper()}")

    if assertions == case.assertions:
        return case
    return case.model_copy(update={"assertions": assertions})


def _fields_after_keywords(text: str, *, include: bool) -> list[str]:
    keywords = ("包含", "包括", "存在", "提供") if include else (
        "不返回",
        "不应包含",
        "应缺失",
        "应不存在",
        "不提供",
        "不包含",
    )
    field_token = rf"(?:[A-Za-z][A-Za-z0-9_]*|{'|'.join(map(re.escape, _FIELD_ALIASES))})"
    pattern = re.compile(
        rf"(?:{'|'.join(keywords)})\s*({field_token}"
        rf"(?:\s*(?:、|,|，|和|及|以及)\s*{field_token})*)",
        re.IGNORECASE,
    )
    fields: list[str] = []
    for match in pattern.finditer(text):
        for token in re.split(r"[、,，和及以及\s]+", match.group(1)):
            if not token:
                continue
            fields.append(_FIELD_ALIASES.get(token, token))
    return list(dict.fromkeys(fields))


def _normalize_existing_assertions(
    assertions: Iterable[Assertion],
    *,
    declared_fields: set[str],
    absent_fields: set[str],
) -> list[Assertion]:
    """按当前测试点明确的字段语义校正路径并移除显式矛盾。

    只处理需求文本已经明确出现的字段别名；不会把任意 snake_case
    和 camelCase 全局视为等价，也不会根据接口名称猜字段。
    """

    normalized: list[Assertion] = []
    for assertion in assertions:
        path = _canonicalize_declared_field_path(assertion.path, declared_fields)
        candidate = (
            assertion.model_copy(update={"path": path})
            if path != assertion.path
            else assertion
        )
        if (
            candidate.type == "json_exists"
            and candidate.expected is True
            and _path_field(candidate.path) in absent_fields
        ):
            continue
        normalized.append(candidate)
    return normalized


def _canonicalize_declared_field_path(path: str | None, fields: set[str]) -> str | None:
    if not path:
        return path
    normalized = path
    for field in fields:
        snake_case = re.sub(r"(?<!^)([A-Z])", r"_\1", field).lower()
        for spelling in {field, snake_case}:
            normalized = normalized.replace(f".{spelling}", f".{field}")
    return normalized


def _path_field(path: str | None) -> str | None:
    if not path or "." not in path:
        return None
    return path.rsplit(".", 1)[-1]


def _absent_field_path_prefix(
    assertions: Iterable[Assertion],
    absent_fields: set[str],
) -> str:
    """复用已有缺失字段断言的数组/对象层级，避免改变响应结构语义。"""

    for assertion in assertions:
        if assertion.type != "json_exists" or assertion.expected is not False:
            continue
        field = _path_field(assertion.path)
        if field in absent_fields and assertion.path:
            return assertion.path[: -len(field)]
    return "$.data."


def _assertion_signature(assertion: Assertion) -> tuple[object, ...]:
    # expected 可能是 response_schema/json_contains 等结构化值，不能直接放进 set。
    expected = json.dumps(
        assertion.expected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return (assertion.type, assertion.path, assertion.operator, expected)
