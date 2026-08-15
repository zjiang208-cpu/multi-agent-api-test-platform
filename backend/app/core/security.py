from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "dsn",
)
SENSITIVE_TEXT = re.compile(
    r"(?i)(\b(?:password|passwd|secret|token|api[_-]?key|authorization|dsn)\b\s*[:=]\s*)([^\s,;]+)"
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a display-safe copy without exposing secret-like values."""

    result: dict[str, Any] = {}
    for key, item in value.items():
        result[key] = "<redacted>" if is_sensitive_key(key) else sanitize_value(item)
    return result


def sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_text(value: str, *, max_length: int = 20_000) -> str:
    """Bound and mask secret-like assignments inside human-authored text."""

    return SENSITIVE_TEXT.sub(r"\1<redacted>", value)[:max_length]
