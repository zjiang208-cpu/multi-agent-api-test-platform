from __future__ import annotations

from urllib.parse import urlparse

import httpx


class ExecutionPolicyError(ValueError):
    pass


class TargetPolicy:
    """Shared outbound HTTP target policy for execution and authentication."""

    def __init__(self, *, allow_remote_targets: bool = False) -> None:
        self.allow_remote_targets = allow_remote_targets

    def validate(self, target: str, *, require_clean_base: bool = False) -> None:
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ExecutionPolicyError("target base URL must be HTTP(S) with a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ExecutionPolicyError("target base URL must not contain credentials")
        if require_clean_base and (parsed.query or parsed.fragment):
            raise ExecutionPolicyError("target base URL must not contain a query or fragment")
        if self.allow_remote_targets:
            return
        if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
            raise ExecutionPolicyError("remote targets are disabled")

    async def validate_request(self, request: httpx.Request) -> None:
        """Validate initial requests and every redirect before transmission."""

        self.validate(str(request.url))
