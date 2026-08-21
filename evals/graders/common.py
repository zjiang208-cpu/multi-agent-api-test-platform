from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def ratio(
    numerator: int | float,
    denominator: int | float,
    *,
    pending_reason: str | None = None,
) -> dict[str, Any]:
    if pending_reason:
        return {
            "value": None,
            "numerator": numerator,
            "denominator": denominator,
            "status": "pending_annotation",
            "reason": pending_reason,
        }
    if denominator == 0:
        return {
            "value": None,
            "numerator": numerator,
            "denominator": denominator,
            "status": "pending_input",
            "reason": "metric denominator is zero",
        }
    return {
        "value": round(float(numerator) / float(denominator), 4),
        "numerator": numerator,
        "denominator": denominator,
        "status": "ready",
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def case_fingerprint(case: Any) -> str:
    """Fingerprint the executable behavior, not the linked test-point labels."""

    request = getattr(case, "request", {}) or {}
    assertions = getattr(case, "assertions", []) or []
    payload = {
        "request": request,
        "assertions": sorted(
            [
                {
                    "type": getattr(assertion, "type", None),
                    "path": getattr(assertion, "path", None),
                    "operator": getattr(assertion, "operator", None),
                    "expected": getattr(assertion, "expected", None),
                }
                for assertion in assertions
            ],
            key=canonical_json,
        ),
        "side_effect": bool(getattr(case, "side_effect", False)),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def annotation_pending(manifest_status: str, operation_status: str) -> str | None:
    if manifest_status != "verified":
        return "dataset annotation_status is not verified"
    if operation_status != "verified":
        return "operation annotation_status is not verified"
    return None


def reviewer_id_findings(reviewer: Any) -> dict[str, list[str]]:
    if reviewer is None:
        return {}
    fields = (
        "missing_test_point_ids",
        "invalid_case_ids",
        "duplicate_case_ids",
        "unsupported_assertion_ids",
    )
    return {
        field: [str(item) for item in (getattr(reviewer, field, []) or [])]
        for field in fields
    }


def flatten_mapping(mapping: Mapping[str, list[str]]) -> set[str]:
    return {item for values in mapping.values() for item in values}
