from __future__ import annotations

import operator
import re
from collections.abc import Mapping
from typing import Any

from app.models.cases import Assertion
from app.models.execution import AssertionResult


class AssertionEvaluationError(ValueError):
    pass


def read_json_path(value: Any, path: str) -> Any:
    if path == "$":
        return value
    if not path or not path.startswith("$"):
        raise AssertionEvaluationError(f"JSON path must start with $: {path}")
    current = value
    normalized = path[1:] if path.startswith("$") else path
    normalized = normalized[1:] if normalized.startswith(".") else normalized
    tokens: list[str] = []
    for match in re.finditer(r"[^.\[\]]+|\[(\d+)\]", normalized):
        tokens.append(match.group(1) or match.group(0))
    if not tokens:
        raise AssertionEvaluationError(f"invalid JSON path: {path}")
    for token in tokens:
        key: str | int = int(token) if token.isdigit() else token
        if isinstance(key, int):
            if not isinstance(current, list) or key >= len(current):
                raise KeyError(path)
            current = current[key]
        else:
            if not isinstance(current, Mapping) or key not in current:
                raise KeyError(path)
            current = current[key]
    return current


def _compare(actual: Any, expected: Any, expression: str | None) -> bool:
    normalized = (expression or "eq").strip().lower()
    if normalized in {"=", "==", "eq", "equals"}:
        return actual == expected
    if normalized in {"!=", "<>", "ne", "not_equals"}:
        return actual != expected
    if normalized == "between":
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            raise AssertionEvaluationError("between requires a two-item expected range")
        return expected[0] <= actual <= expected[1]
    operators = {
        "<=": operator.le,
        "le": operator.le,
        ">=": operator.ge,
        "ge": operator.ge,
        "<": operator.lt,
        "lt": operator.lt,
        ">": operator.gt,
        "gt": operator.gt,
    }
    compare = operators.get(normalized)
    if compare is None:
        raise AssertionEvaluationError(f"unsupported assertion operator: {expression}")
    return compare(actual, expected)


def evaluate_assertion(assertion: Assertion, *, status_code: int, headers: Mapping[str, str], body: Any, duration_ms: float) -> AssertionResult:
    try:
        if assertion.type == "status_code":
            passed = _compare(status_code, assertion.expected, assertion.operator)
            actual = status_code
        elif assertion.type == "json_exists":
            try:
                read_json_path(body, assertion.path or "")
                passed = True
                actual = True
            except (KeyError, IndexError):
                passed = False
                actual = False
        elif assertion.type in {"json_value", "json_type", "json_contains"}:
            actual = read_json_path(body, assertion.path or "")
            if assertion.type == "json_value":
                passed = _compare(actual, assertion.expected, assertion.operator)
            elif assertion.type == "json_type":
                type_names = {
                    "string": str,
                    "number": (int, float),
                    "integer": int,
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                    "null": type(None),
                }
                expected_type = type_names.get(str(assertion.expected))
                passed = (
                    expected_type is not None
                    and isinstance(actual, expected_type)
                    and not (
                        str(assertion.expected) in {"integer", "number"}
                        and isinstance(actual, bool)
                    )
                )
            else:
                passed = assertion.expected in actual
        elif assertion.type == "header_value":
            actual = next((value for key, value in headers.items() if key.lower() == (assertion.path or "").lower()), None)
            passed = _compare(actual, assertion.expected, assertion.operator)
        elif assertion.type == "response_time_ms":
            actual = duration_ms
            passed = _compare(actual, assertion.expected, assertion.operator or "<=")
        elif assertion.type == "response_schema":
            actual = read_json_path(body, assertion.path) if assertion.path else body
            passed = _matches_schema(actual, assertion.expected)
        else:
            raise AssertionEvaluationError(f"unsupported assertion type: {assertion.type}")
        return AssertionResult(
            assertion_id=assertion.assertion_id,
            type=assertion.type,
            path=assertion.path,
            operator=assertion.operator,
            evidence_refs=assertion.evidence_refs,
            passed=passed,
            message="assertion passed" if passed else "assertion failed",
            expected=assertion.expected,
            actual=actual,
        )
    except (AssertionEvaluationError, KeyError, IndexError, TypeError) as exc:
        return AssertionResult(
            assertion_id=assertion.assertion_id,
            type=assertion.type,
            path=assertion.path,
            operator=assertion.operator,
            evidence_refs=assertion.evidence_refs,
            passed=False,
            message=f"assertion could not be evaluated: {exc}",
            expected=assertion.expected,
        )


def _matches_schema(value: Any, schema: Any) -> bool:
    if not isinstance(schema, Mapping):
        return False
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        return any(_matches_schema(value, item) for item in any_of)
    schema_type = schema.get("type")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return False
    if schema_type == "object":
        if not isinstance(value, Mapping):
            return False
        required = schema.get("required", [])
        if any(key not in value for key in required):
            return False
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        return all(
            key not in value or _matches_schema(value[key], child)
            for key, child in properties.items()
        )
    if schema_type == "array":
        return isinstance(value, list) and all(_matches_schema(item, schema.get("items", {})) for item in value)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return schema_type is None and (not schema or set(schema) == {"enum"})
