from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.models.cases import TestCase
from app.models.contracts import OperationContract


SUPPORTED_ASSERTIONS = {
    "status_code",
    "json_value",
    "json_type",
    "json_contains",
    "json_exists",
    "header_value",
    "response_schema",
    "response_time_ms",
}

SUPPORTED_OPERATORS = {
    "=",
    "==",
    "eq",
    "equals",
    "!=",
    "<>",
    "ne",
    "not_equals",
    "<",
    "lt",
    "<=",
    "le",
    ">",
    "gt",
    ">=",
    "ge",
    "between",
}

JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}
SUPPORTED_SCHEMA_KEYS = {
    "type",
    "enum",
    "anyOf",
    "properties",
    "required",
    "items",
    "additionalProperties",
}
SIDE_EFFECT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")
_UNRESOLVED_VALUE = re.compile(r"(?:\{\{[^{}]+\}\}|\$\{[^{}]+\}|\b(?:TODO|TBD)\b)", re.IGNORECASE)
_SUPPORTED_JSON_PATH = re.compile(r"^\$(?:\.[^.\[\]]+|\[\d+\])*$")


def validate_case(
    case: TestCase,
    *,
    known_test_points: set[str],
    known_evidence: set[str],
    operation: OperationContract | None = None,
) -> list[str]:
    errors: list[str] = []
    if not case.test_point_ids:
        errors.append("case has no test point references")
    if len(set(case.test_point_ids)) != len(case.test_point_ids):
        errors.append("case has duplicate test point references")
    missing_points = set(case.test_point_ids) - known_test_points
    if missing_points:
        errors.append(f"unknown test points: {sorted(missing_points)}")
    missing_evidence = set(case.evidence_refs) - known_evidence
    if missing_evidence:
        errors.append(f"unknown evidence refs: {sorted(missing_evidence)}")
    if not case.evidence_refs:
        errors.append("case has no evidence references")
    if not case.request.method or not case.request.path.startswith("/"):
        errors.append("request method/path is invalid")
    if operation is not None:
        errors.extend(_validate_request_against_operation(case, operation))
    if _contains_unresolved_value(case.request.path_params):
        errors.append("path parameters contain unresolved placeholders")
    if _contains_unresolved_value(case.request.query_params):
        errors.append("query parameters contain unresolved placeholders")
    if _contains_unresolved_value(case.request.headers):
        errors.append("request headers contain unresolved placeholders")
    if _contains_unresolved_value(case.request.body):
        errors.append("request body contains unresolved placeholders")
    assertion_ids = [assertion.assertion_id for assertion in case.assertions]
    if len(set(assertion_ids)) != len(assertion_ids):
        errors.append("case has duplicate assertion IDs")
    for assertion in case.assertions:
        if assertion.type not in SUPPORTED_ASSERTIONS:
            errors.append(f"unsupported assertion: {assertion.type}")
        if not assertion.evidence_refs:
            errors.append(f"assertion has no evidence references: {assertion.assertion_id}")
        unknown_assertion_evidence = set(assertion.evidence_refs) - known_evidence
        if unknown_assertion_evidence:
            errors.append(
                f"assertion references unknown evidence {sorted(unknown_assertion_evidence)}: "
                f"{assertion.assertion_id}"
            )
        if assertion.type.startswith("json_") and (
            not assertion.path or not assertion.path.startswith("$")
        ):
            errors.append(f"JSON assertion requires a $-prefixed path: {assertion.assertion_id}")
        if (
            assertion.type.startswith("json_")
            and assertion.path
            and not _SUPPORTED_JSON_PATH.fullmatch(assertion.path)
        ):
            errors.append(
                f"JSON assertion uses an unsupported path expression: {assertion.assertion_id}"
            )
        if (
            assertion.type == "json_exists"
            and assertion.expected is not None
            and assertion.expected is not True
        ):
            errors.append(
                f"json_exists only supports expected=true or null: {assertion.assertion_id}"
            )
        if assertion.type == "status_code" and assertion.expected is None:
            errors.append(f"status assertion requires expected status: {assertion.assertion_id}")
        if assertion.type == "status_code" and assertion.path is not None:
            errors.append(f"status assertion must not define a path: {assertion.assertion_id}")
        if assertion.type == "header_value" and not assertion.path:
            errors.append(f"header assertion requires a response header name: {assertion.assertion_id}")
        if assertion.type == "json_type" and assertion.expected not in JSON_TYPES:
            errors.append(f"json_type has unsupported expected type: {assertion.assertion_id}")
        if assertion.type == "response_schema" and not isinstance(assertion.expected, Mapping):
            errors.append(f"response_schema requires an object schema: {assertion.assertion_id}")
        if (
            assertion.type == "response_schema"
            and assertion.path
            and not _SUPPORTED_JSON_PATH.fullmatch(assertion.path)
        ):
            errors.append(
                f"response_schema uses an unsupported path expression: {assertion.assertion_id}"
            )
        if assertion.type == "response_schema" and isinstance(assertion.expected, Mapping):
            errors.extend(
                f"response_schema {error}: {assertion.assertion_id}"
                for error in _validate_response_schema(assertion.expected)
            )
        if assertion.type == "response_time_ms" and not isinstance(assertion.expected, (int, float)):
            errors.append(f"response_time_ms requires a numeric expected value: {assertion.assertion_id}")
        normalized_operator = assertion.operator.strip().lower() if assertion.operator else None
        if normalized_operator and normalized_operator not in SUPPORTED_OPERATORS:
            errors.append(
                f"unsupported assertion operator {assertion.operator}: {assertion.assertion_id}"
            )
        if normalized_operator == "between" and (
            not isinstance(assertion.expected, (list, tuple))
            or len(assertion.expected) != 2
        ):
            errors.append(
                f"between assertion requires a two-item expected range: {assertion.assertion_id}"
            )
    return errors


def _validate_request_against_operation(case: TestCase, operation: OperationContract) -> list[str]:
    errors: list[str] = []
    method = case.request.method
    if method != operation.method:
        errors.append(
            f"request method {case.request.method} does not match operation method {operation.method}"
        )
    if case.request.path != operation.path:
        errors.append(
            f"request path {case.request.path} does not match operation path {operation.path}"
        )

    expected_path_parameters = set(_PATH_PARAMETER.findall(operation.path))
    actual_path_parameters = set(case.request.path_params)
    missing_path_parameters = expected_path_parameters - actual_path_parameters
    extra_path_parameters = actual_path_parameters - expected_path_parameters
    if missing_path_parameters:
        errors.append(f"missing path parameters: {sorted(missing_path_parameters)}")
    if extra_path_parameters:
        errors.append(f"unknown path parameters: {sorted(extra_path_parameters)}")

    containers = {
        "path": case.request.path_params,
        "query": case.request.query_params,
        "header": {name.lower(): value for name, value in case.request.headers.items()},
    }
    for parameter in operation.parameters:
        if not parameter.required or parameter.location not in containers:
            continue
        parameter_name = parameter.name.lower() if parameter.location == "header" else parameter.name
        if parameter_name not in containers[parameter.location]:
            errors.append(
                f"missing required {parameter.location} parameter: {parameter.name}"
            )
            continue
        parameter_value = containers[parameter.location][parameter_name]
        if parameter_value is None or (
            isinstance(parameter_value, str) and not parameter_value.strip()
        ):
            errors.append(
                f"required {parameter.location} parameter has no concrete value: "
                f"{parameter.name}"
            )

    if operation.method in SIDE_EFFECT_METHODS:
        if not case.side_effect:
            errors.append(f"{method} cases must be marked as side-effecting")
        if not case.side_effect_note:
            errors.append("side-effecting case requires side_effect_note")
    elif case.side_effect and not case.side_effect_note:
        errors.append("side_effect=true requires side_effect_note")
    return errors


def _contains_unresolved_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_UNRESOLVED_VALUE.search(value))
    if isinstance(value, Mapping):
        return any(_contains_unresolved_value(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_unresolved_value(item) for item in value)
    return False


def _validate_response_schema(schema: Mapping[str, Any], location: str = "$") -> list[str]:
    errors: list[str] = []
    unknown_keys = set(schema) - SUPPORTED_SCHEMA_KEYS
    if unknown_keys:
        errors.append(f"uses unsupported keywords at {location}: {sorted(unknown_keys)}")
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in JSON_TYPES:
        errors.append(f"uses unsupported type at {location}: {schema_type}")
    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list) or not all(isinstance(item, str) for item in required)
    ):
        errors.append(f"requires a string list at {location}.required")
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        errors.append(f"requires a boolean at {location}.additionalProperties")
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            errors.append(f"requires an object at {location}.properties")
        else:
            for key, child in properties.items():
                if not isinstance(child, Mapping):
                    errors.append(f"requires an object at {location}.properties.{key}")
                else:
                    errors.extend(
                        _validate_response_schema(child, f"{location}.properties.{key}")
                    )
    items = schema.get("items")
    if items is not None:
        if not isinstance(items, Mapping):
            errors.append(f"requires an object at {location}.items")
        else:
            errors.extend(_validate_response_schema(items, f"{location}.items"))
    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or not all(isinstance(item, Mapping) for item in any_of):
            errors.append(f"requires an object list at {location}.anyOf")
        else:
            for index, child in enumerate(any_of):
                errors.extend(_validate_response_schema(child, f"{location}.anyOf[{index}]"))
    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list):
        errors.append(f"requires a list at {location}.enum")
    return errors
