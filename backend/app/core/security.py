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
SAFE_FIXTURE_VALUE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9_-]*\s+)?\$(?:AUTH_FIXTURE|DB_FIXTURE)\[[^\]\r\n]+\]$"
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a display-safe copy without exposing secret-like values."""

    result: dict[str, Any] = {}
    for key, item in value.items():
        if is_sensitive_key(key):
            # Fixture placeholders are deliberately non-secret and must remain
            # visible to downstream agents so they can design deterministic
            # negative-auth/database cases. Real credentials remain masked.
            if isinstance(item, str) and SAFE_FIXTURE_VALUE.fullmatch(item.strip()):
                result[key] = item
            else:
                result[key] = "<redacted>"
        else:
            result[key] = sanitize_value(item)
    return result


def sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_text(value: str, *, max_length: int = 20_000) -> str:
    """Bound and mask secret-like assignments inside human-authored text."""

    def replace(match: re.Match[str]) -> str:
        prefix, sensitive_value = match.group(1), match.group(2)
        if SAFE_FIXTURE_VALUE.fullmatch(sensitive_value.strip()):
            return f"{prefix}{sensitive_value}"
        return f"{prefix}<redacted>"

    return SENSITIVE_TEXT.sub(replace, value)[:max_length]
