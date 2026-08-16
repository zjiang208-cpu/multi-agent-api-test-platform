from __future__ import annotations

import json
import re
import time
from uuid import uuid4

import httpx

from app.assertions.engine import evaluate_assertion
from app.models.cases import TestCase
from app.models.execution import ExecutionResult
from app.models.projects import ProjectSettings
from app.executor.policy import ExecutionPolicyError, TargetPolicy
from app.providers.llm import resolve_secret_reference


_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authenticate",
    "proxy-authorization",
    "set-cookie",
    "www-authenticate",
    "x-api-key",
}
_SENSITIVE_BODY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "token",
}
_REDACTED = "[REDACTED]"
_AUTH_PLACEHOLDER_MARKERS = ("<redacted>", "<token>", "${token}", "$TOKEN", "YOUR_TOKEN")
_AUTH_FIXTURE_RE = re.compile(r"\$AUTH_FIXTURE\[(?P<kind>nonexistent|expired):token\]")


class HttpExecutor:
    def __init__(
        self,
        *,
        allow_remote_targets: bool = False,
        max_response_body_length: int = 12_000,
        transport=None,
        auth_token: str | None = None,
        auth_prefix: str | None = None,
        auth_location: str = "header",
        auth_name: str = "Authorization",
    ) -> None:
        self.allow_remote_targets = allow_remote_targets
        self.target_policy = TargetPolicy(allow_remote_targets=allow_remote_targets)
        self.max_response_body_length = max_response_body_length
        self.transport = transport
        self.auth_token = auth_token
        self.auth_prefix = auth_prefix
        self.auth_location = auth_location
        self.auth_name = auth_name

    async def execute(self, case: TestCase, settings: ProjectSettings) -> ExecutionResult:
        started = time.perf_counter()
        target = str(settings.sut_target.base_url).rstrip("/")
        url = target
        try:
            self._check_target(target, require_clean_base=True)
            url = self._render_url(target, case.request.path, case.request.path_params)
            headers = {
                name: self._resolve_auth_fixture(value, settings)
                for name, value in case.request.headers.items()
            }
            if not self._expects_unauthorized(case):
                if self.auth_token and self.auth_location == "cookie":
                    self._inject_cookie(headers, self.auth_name, self.auth_token)
                else:
                    auth_name = self.auth_name if self.auth_token else "Authorization"
                    auth_key = next(
                        (key for key in headers if key.lower() == auth_name.lower()),
                        None,
                    )
                    if self.auth_token:
                        # A generated case may still contain a stale literal
                        # such as ``Bearer test-token``. Once an Auth Provider
                        # has resolved credentials, it is the source of truth
                        # for authenticated cases, so replace any case-level
                        # value instead of relying on placeholder spelling.
                        headers.pop(auth_key, None) if auth_key else None
                        headers[auth_name] = self._format_auth_value(self.auth_token, self.auth_prefix)
                    elif settings.sut_target.auth_ref:
                        authorization_key = next(
                            (key for key in headers if key.lower() == "authorization"),
                            None,
                        )
                        authorization_value = headers.get(authorization_key) if authorization_key else None
                        if authorization_key is None or self._is_auth_placeholder(authorization_value):
                            if authorization_key:
                                headers.pop(authorization_key, None)
                            headers["Authorization"] = f"Bearer {resolve_secret_reference(settings.sut_target.auth_ref)}"
            async with httpx.AsyncClient(
                follow_redirects=settings.sut_target.allow_redirects,
                verify=settings.sut_target.verify_tls,
                timeout=settings.sut_target.timeout_seconds,
                transport=self.transport,
                event_hooks={"request": [self._validate_outgoing_request]},
            ) as client:
                response = await client.request(
                    method=case.request.method,
                    url=url,
                    params=case.request.query_params,
                    headers=headers,
                    json=case.request.body,
                )
            duration_ms = (time.perf_counter() - started) * 1000
            body = self._response_body(response)
            assertion_results = [
                evaluate_assertion(
                    assertion,
                    status_code=response.status_code,
                    headers=response.headers,
                    body=body,
                    duration_ms=duration_ms,
                )
                for assertion in case.assertions
            ]
            status = "passed" if all(item.passed for item in assertion_results) else "failed"
            return ExecutionResult(
                result_id=f"result-{uuid4().hex}",
                case_id=case.case_id,
                case_title=case.title,
                requirement_id=case.requirement_id,
                status=status,
                method=case.request.method,
                url=url,
                status_code=response.status_code,
                response_headers=self._redact_headers(response.headers),
                response_body=self._redact_body(body),
                duration_ms=duration_ms,
                assertion_results=assertion_results,
            )
        except httpx.TimeoutException:
            return self._error(case, url, "timeout", "request timed out", started)
        except ExecutionPolicyError as exc:
            return self._error(case, url, "transport_error", str(exc), started)
        except httpx.HTTPError:
            return self._error(case, url, "transport_error", "HTTP transport error", started)
        except ValueError:
            return self._error(case, url, "transport_error", "invalid request configuration", started)

    def validate_target(self, base_url: str) -> None:
        """Validate a Human Gate target without sending a request."""

        self._check_target(base_url.rstrip("/"), require_clean_base=True)

    def _check_target(self, target: str, *, require_clean_base: bool = False) -> None:
        self.target_policy.validate(target, require_clean_base=require_clean_base)

    async def _validate_outgoing_request(self, request: httpx.Request) -> None:
        """Apply the target policy to the initial request and every redirect."""

        await self.target_policy.validate_request(request)

    @staticmethod
    def _render_url(base_url: str, path: str, path_params: dict[str, object]) -> str:
        rendered = path
        for name, value in path_params.items():
            rendered = rendered.replace("{" + name + "}", str(value))
        if "{" in rendered or "}" in rendered:
            raise ExecutionPolicyError("unresolved path parameter remains in request path")
        return base_url + (rendered if rendered.startswith("/") else "/" + rendered)

    @staticmethod
    def _is_auth_placeholder(value: str | None) -> bool:
        if not value:
            return False
        lowered = value.casefold()
        return any(marker.casefold() in lowered for marker in _AUTH_PLACEHOLDER_MARKERS)

    @staticmethod
    def _expects_unauthorized(case: TestCase) -> bool:
        """Keep explicit unauthenticated/invalid-auth cases unauthenticated."""

        return any(
            assertion.type == "status_code"
            and str(assertion.expected) in {"401", "403"}
            for assertion in case.assertions
        )

    @staticmethod
    def _format_auth_value(token: str, prefix: str | None) -> str:
        return f"{prefix} {token}".strip() if prefix else token

    @classmethod
    def _resolve_auth_fixture(cls, value: str, settings: ProjectSettings) -> str:
        def replace(match: re.Match[str]) -> str:
            kind = match.group("kind")
            if kind == "nonexistent":
                return f"__api_test_nonexistent_token_{uuid4().hex}__"
            reference = settings.auth_provider.negative_fixtures.expired_token_ref
            if not reference:
                raise ValueError("expired authentication fixture is not configured")
            return resolve_secret_reference(reference)

        return _AUTH_FIXTURE_RE.sub(replace, value)

    @classmethod
    def _inject_cookie(cls, headers: dict[str, str], name: str, value: str) -> None:
        cookie_key = next((key for key in headers if key.lower() == "cookie"), "Cookie")
        entries = [item.strip() for item in headers.get(cookie_key, "").split(";") if item.strip()]
        replaced = False
        rendered: list[str] = []
        for entry in entries:
            cookie_name, _, cookie_value = entry.partition("=")
            if cookie_name.strip().lower() == name.lower():
                rendered.append(f"{name}={value}")
                replaced = True
            else:
                rendered.append(entry)
        if not replaced:
            rendered.append(f"{name}={value}")
        headers[cookie_key] = "; ".join(rendered)

    def _response_body(self, response: httpx.Response):
        content = response.content[: self.max_response_body_length]
        if response.headers.get("content-type", "").lower().startswith("application/json"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content.decode("utf-8", errors="replace")
        return content.decode("utf-8", errors="replace")

    @staticmethod
    def _redact_headers(headers: httpx.Headers) -> dict[str, str]:
        return {
            key: _REDACTED if key.lower() in _SENSITIVE_HEADER_NAMES else value
            for key, value in headers.items()
        }

    @classmethod
    def _redact_body(cls, value):
        if isinstance(value, dict):
            return {
                key: (
                    _REDACTED
                    if str(key).lower().replace("-", "_") in _SENSITIVE_BODY_KEYS
                    else cls._redact_body(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact_body(item) for item in value]
        return value

    @staticmethod
    def _error(case, url, category, message, started):
        return ExecutionResult(
            result_id=f"result-{uuid4().hex}",
            case_id=case.case_id,
            case_title=case.title,
            requirement_id=case.requirement_id,
            status="error",
            method=case.request.method,
            url=url,
            error_category=category,
            error_message=message[:1000],
            duration_ms=(time.perf_counter() - started) * 1000,
        )
