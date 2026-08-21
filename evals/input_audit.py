from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_SAFE_REDACTION = re.compile(
    r"^(?:<redacted>|<token>|\$TOKEN|\$\{token\}|\$DB_FIXTURE\[[^\]\r\n]+\]|\$AUTH_FIXTURE\[[^\]\r\n]+\])$",
    re.IGNORECASE,
)
_JWT = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_SENSITIVE_FIELDS = {
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "dsn",
    "database_url",
    "raw_output",
    "model_output",
    "prompt",
    "completion",
    "response_body",
    "response_headers",
}


def audit_input_payload(payload: Any) -> dict[str, Any]:
    """检查评测输入是否只包含脱敏内容，不自动改写原始文件。"""

    issues: list[dict[str, str]] = []
    _walk(payload, "$", issues)
    return {
        "status": "ready" if not issues else "needs_redaction",
        "issues": issues,
        "notes": [
            "该审计只检查输入结构和明显敏感字段，不替换或覆盖原始文件。",
            "通过审计不等于业务语义已经完成 Ground Truth 标注。",
        ],
    }


def _walk(value: Any, path: str, issues: list[dict[str, str]]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized_key = str(key).strip().lower()
            if normalized_key in _SENSITIVE_FIELDS and not _is_safe_redaction(child):
                issue_type = (
                    "raw_artifact"
                    if normalized_key
                    in {"raw_output", "model_output", "prompt", "completion", "response_body", "response_headers"}
                    else "sensitive_field"
                )
                issues.append(
                    {
                        "type": issue_type,
                        "path": child_path,
                        "message": "敏感字段必须使用脱敏占位符，不能直接进入离线评测。",
                    }
                )
            _walk(child, child_path, issues)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _walk(child, f"{path}[{index}]", issues)
        return
    if isinstance(value, str) and (_JWT.fullmatch(value.strip()) or value.strip().lower().startswith("bearer ")):
        issues.append(
            {
                "type": "secret_like_value",
                "path": path,
                "message": "检测到疑似 Token 值，请先替换为脱敏占位符。",
            }
        )


def _is_safe_redaction(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return bool(_SAFE_REDACTION.fullmatch(value.strip()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_is_safe_redaction(item) for item in value)
    if isinstance(value, Mapping):
        return all(_is_safe_redaction(item) for item in value.values())
    return False
