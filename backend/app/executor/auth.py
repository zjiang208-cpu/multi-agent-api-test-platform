from __future__ import annotations

import asyncio
import os
import re
import socket
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx

from app.assertions.engine import AssertionEvaluationError, read_json_path
from app.executor.policy import ExecutionPolicyError, TargetPolicy
from app.models.cases import TestCase
from app.models.projects import AuthProviderSettings, ProjectSettings
from app.providers.llm import SecretReferenceError, resolve_secret_reference


_AUTH_WORDS = (
    "authorization",
    "token",
    "\u767b\u5f55",
    "\u9274\u6743",
    "\u8ba4\u8bc1",
    "\u9700\u8981\u767b\u5f55",
    "login",
    "auth",
)
_ENV_TOKEN_NAMES = (
    "API_TEST_AUTH_TOKEN",
    "TEST_API_AUTH_TOKEN",
)


class AutomaticAuthenticationError(RuntimeError):
    """Raised when an authenticated test needs a token but local login failed."""


@dataclass(frozen=True)
class AuthCredentials:
    token: str
    prefix: str | None = None
    location: str = "header"
    name: str = "Authorization"

    @property
    def header_value(self) -> str:
        return f"{self.prefix} {self.token}".strip() if self.prefix else self.token


@dataclass(frozen=True)
class _CachedCredentials:
    credentials: AuthCredentials
    expires_at: float | None


class AutomaticAuthProvider:
    """Resolve a local test token without exposing credentials to the LLM or UI.

    A configured HTTP or SMS provider is language-agnostic: it sends the
    declared authentication requests, extracts a token/cookie/header, and
    injects it into test requests. Unconfigured projects may still use an
    explicit environment token as a simple fallback.
    """

    def __init__(self, *, allow_remote_targets: bool = False) -> None:
        self._cache: dict[tuple[str, str], _CachedCredentials] = {}
        self._project_store: Any | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_retry_at: dict[tuple[str, str], float] = {}
        self._target_policy = TargetPolicy(allow_remote_targets=allow_remote_targets)

    def start(self, project_store: Any) -> None:
        """Start the backend-lifetime refresh loop for configured projects."""

        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._project_store = project_store
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(),
            name="auth-token-refresh",
        )

    async def stop(self) -> None:
        """Stop background refresh when the backend is shutting down."""

        task = self._refresh_task
        self._refresh_task = None
        self._project_store = None
        self._refresh_retry_at.clear()
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _refresh_loop(self) -> None:
        # The first pass starts the TTL clock from backend startup and obtains
        # tokens for projects whose provider is fully configured. Later passes
        # refresh only cached credentials whose TTL has elapsed.
        await self._refresh_projects(force=True)
        while True:
            await asyncio.sleep(1)
            await self._refresh_projects(force=False)

    async def _refresh_projects(self, *, force: bool) -> None:
        if self._project_store is None:
            return
        try:
            projects = self._project_store.list()
        except Exception:
            return
        now = time.monotonic()
        for project in projects:
            provider = project.settings.auth_provider
            if (
                not provider.enabled
                or provider.token_ttl_seconds is None
                or project.settings.sut_target.auth_ref
            ):
                continue
            if provider.kind == "http" and provider.login is None:
                continue
            base_url = str(project.settings.sut_target.base_url).rstrip("/")
            key = self._cache_key(project.project_id, base_url)
            cached = self._cache.get(key)
            due = cached is None or (
                cached.expires_at is not None and cached.expires_at <= now
            )
            if not due or (not force and self._refresh_retry_at.get(key, 0.0) > now):
                continue
            try:
                await self.resolve(
                    project.settings,
                    project_id=project.project_id,
                    base_url=base_url,
                    cases=[],
                )
                self._refresh_retry_at.pop(key, None)
            except AutomaticAuthenticationError:
                # The first execution will surface the configuration error to
                # the user; a background refresh must not stop the server. A
                # short retry delay also lets a newly saved configuration take
                # effect without hammering an unavailable login endpoint.
                self._refresh_retry_at[key] = now + 5.0
                continue

    async def resolve(
        self,
        settings: ProjectSettings,
        *,
        project_id: str,
        base_url: str,
        cases: list[TestCase],
    ) -> AuthCredentials | None:
        # An explicit project reference remains the source of truth. The
        # automatic flow is only a fallback for model-redacted credentials.
        if settings.sut_target.auth_ref:
            return None
        configured = settings.auth_provider
        cache_key = self._cache_key(project_id, base_url)
        if configured.enabled:
            self._validate_target(base_url)
            cached = self._cache.get(cache_key)
            if cached and (cached.expires_at is None or cached.expires_at > time.monotonic()):
                return cached.credentials
            if cached:
                self._cache.pop(cache_key, None)
            if configured.kind == "sms":
                credentials = await self._resolve_sms(settings, base_url, configured)
            else:
                credentials = await self._resolve_configured_http(settings, base_url, configured)
            self._cache[cache_key] = _CachedCredentials(
                credentials=credentials,
                expires_at=self._expires_at(configured),
            )
            return credentials

        if not self._needs_auth(cases):
            return None

        cached = self._cache.get(cache_key)
        if cached:
            return cached.credentials

        explicit = self._environment_token()
        if explicit:
            self._cache[cache_key] = _CachedCredentials(credentials=explicit, expires_at=None)
            return explicit

        raise AutomaticAuthenticationError(
            "authenticated cases require auth_provider, auth_ref, or API_TEST_AUTH_TOKEN"
        )

    def invalidate(self, project_id: str, base_url: str) -> None:
        """Forget a cached credential after the target rejects it."""

        key = self._cache_key(project_id, base_url)
        self._cache.pop(key, None)
        self._refresh_retry_at.pop(key, None)

    @staticmethod
    def _cache_key(project_id: str, base_url: str) -> tuple[str, str]:
        return project_id, base_url.rstrip("/").casefold()

    def _validate_target(self, base_url: str) -> None:
        try:
            self._target_policy.validate(base_url.rstrip("/"), require_clean_base=True)
        except ExecutionPolicyError as exc:
            raise AutomaticAuthenticationError(str(exc)) from exc

    async def _validate_outgoing_request(self, request: httpx.Request) -> None:
        await self._target_policy.validate_request(request)

    @staticmethod
    def _expires_at(provider: AuthProviderSettings) -> float | None:
        if provider.token_ttl_seconds is None:
            return None
        return time.monotonic() + provider.token_ttl_seconds

    @staticmethod
    def _needs_auth(cases: list[TestCase]) -> bool:
        for case in cases:
            values: list[str] = [
                case.title,
                case.expected_behavior,
                *case.preconditions,
                *case.steps,
                *case.request.headers.values(),
            ]
            text = " ".join(values).casefold()
            if any(word.casefold() in text for word in _AUTH_WORDS):
                return True
        return False

    @staticmethod
    def _environment_token() -> AuthCredentials | None:
        for name in _ENV_TOKEN_NAMES:
            token = os.getenv(name)
            if token:
                prefix = os.getenv(f"{name}_PREFIX", "Bearer").strip() or None
                return AuthCredentials(token=token.strip(), prefix=prefix)
        return None

    async def _resolve_configured_http(
        self,
        settings: ProjectSettings,
        base_url: str,
        provider: AuthProviderSettings,
    ) -> AuthCredentials:
        login = provider.login
        if login is None:
            raise AutomaticAuthenticationError(
                "the HTTP Auth Provider is enabled but no login request is configured"
            )
        try:
            credentials = {
                name: resolve_secret_reference(reference)
                for name, reference in login.credential_refs.items()
            }
        except SecretReferenceError as exc:
            raise AutomaticAuthenticationError(
                "an Auth Provider credential reference is unavailable"
            ) from exc
        rendered_body = self._render_template(login.body, credentials)
        request = {
            "method": login.method.upper(),
            "url": self._join_url(base_url, login.path),
            "params": self._render_template(login.query_params, credentials),
            "headers": self._render_template(login.headers, credentials),
        }
        if login.body_type == "json":
            request["json"] = rendered_body
        elif login.body_type == "form":
            request["data"] = rendered_body
        try:
            async with httpx.AsyncClient(
                timeout=settings.sut_target.timeout_seconds,
                follow_redirects=settings.sut_target.allow_redirects,
                verify=settings.sut_target.verify_tls,
                event_hooks={"request": [self._validate_outgoing_request]},
            ) as client:
                response = await client.request(**request)
        except ExecutionPolicyError as exc:
            raise AutomaticAuthenticationError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AutomaticAuthenticationError(
                "the configured Auth Provider could not reach its login endpoint"
            ) from exc
        if response.status_code >= 400:
            raise AutomaticAuthenticationError(
                f"the configured Auth Provider login failed (HTTP {response.status_code})"
            )
        value = self._extract_credential(response, provider)
        if value is None or not str(value).strip():
            raise AutomaticAuthenticationError(
                "the configured Auth Provider could not extract a credential from the login response"
            )
        return AuthCredentials(
            token=str(value),
            prefix=provider.inject.prefix if provider.inject.location == "header" else None,
            location=provider.inject.location,
            name=provider.inject.name,
        )

    async def _resolve_sms(
        self,
        settings: ProjectSettings,
        base_url: str,
        provider: AuthProviderSettings,
    ) -> AuthCredentials:
        sms = provider.sms
        try:
            phone = resolve_secret_reference(sms.phone_ref)
        except SecretReferenceError as exc:
            raise AutomaticAuthenticationError(
                f"the SMS Auth Provider phone reference is unavailable: {sms.phone_ref}"
            ) from exc
        credentials: dict[str, str] = {"phone": phone}
        credentials.update(self._resolve_credential_refs(sms.code_request.credential_refs))
        code_response = await self._send_auth_request(
            settings,
            base_url,
            sms.code_request,
            credentials,
        )
        if code_response.status_code >= 400:
            raise AutomaticAuthenticationError(
                f"the SMS code request failed (HTTP {code_response.status_code})"
            )
        if sms.code_source == "redis":
            try:
                redis_password = (
                    resolve_secret_reference(sms.redis_password_ref)
                    if sms.redis_password_ref
                    else ""
                )
                code = await asyncio.to_thread(
                    _redis_get,
                    sms.redis_host,
                    sms.redis_port,
                    redis_password,
                    self._render_template(sms.code_path, credentials),
                )
            except (SecretReferenceError, ConnectionError, OSError) as exc:
                raise AutomaticAuthenticationError(
                    "the SMS code could not be read from the configured Redis store"
                ) from exc
        else:
            try:
                code = read_json_path(code_response.json(), sms.code_path)
            except (ValueError, AssertionEvaluationError, KeyError, IndexError, TypeError):
                code = None
        if code is None or not str(code).strip():
            raise AutomaticAuthenticationError(
                "the SMS code source did not contain a usable verification code"
            )
        credentials["code"] = str(code)
        credentials.update(self._resolve_credential_refs(sms.login.credential_refs))
        login_response = await self._send_auth_request(
            settings,
            base_url,
            sms.login,
            credentials,
        )
        if login_response.status_code >= 400:
            raise AutomaticAuthenticationError(
                f"the SMS login request failed (HTTP {login_response.status_code})"
            )
        value = self._extract_credential(login_response, provider)
        if value is None or not str(value).strip():
            raise AutomaticAuthenticationError(
                "the SMS login response did not contain a usable credential"
            )
        return AuthCredentials(
            token=str(value),
            prefix=provider.inject.prefix if provider.inject.location == "header" else None,
            location=provider.inject.location,
            name=provider.inject.name,
        )

    @staticmethod
    def _resolve_credential_refs(refs: dict[str, str]) -> dict[str, str]:
        try:
            return {name: resolve_secret_reference(reference) for name, reference in refs.items()}
        except SecretReferenceError as exc:
            raise AutomaticAuthenticationError(
                "an Auth Provider credential reference is unavailable"
            ) from exc

    async def _send_auth_request(
        self,
        settings: ProjectSettings,
        base_url: str,
        request_spec,
        credentials: dict[str, str],
    ) -> httpx.Response:
        rendered_body = self._render_template(request_spec.body, credentials)
        request = {
            "method": request_spec.method.upper(),
            "url": self._join_url(base_url, request_spec.path),
            "params": self._render_template(request_spec.query_params, credentials),
            "headers": self._render_template(request_spec.headers, credentials),
        }
        if request_spec.body_type == "json":
            request["json"] = rendered_body
        elif request_spec.body_type == "form":
            request["data"] = rendered_body
        try:
            async with httpx.AsyncClient(
                timeout=settings.sut_target.timeout_seconds,
                follow_redirects=settings.sut_target.allow_redirects,
                verify=settings.sut_target.verify_tls,
                event_hooks={"request": [self._validate_outgoing_request]},
            ) as client:
                return await client.request(**request)
        except ExecutionPolicyError as exc:
            raise AutomaticAuthenticationError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AutomaticAuthenticationError(
                "the configured Auth Provider could not reach its login endpoint"
            ) from exc

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        return base_url.rstrip("/") + (path if path.startswith("/") else f"/{path}")

    @classmethod
    def _render_template(cls, value: Any, credentials: dict[str, str]) -> Any:
        if isinstance(value, str):
            exact = re.fullmatch(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}", value)
            if exact:
                key = exact.group(1)
                if key not in credentials:
                    raise AutomaticAuthenticationError(
                        f"the Auth Provider request references an unknown credential: {key}"
                    )
                return credentials[key]

            def replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in credentials:
                    raise AutomaticAuthenticationError(
                        f"the Auth Provider request references an unknown credential: {key}"
                    )
                return credentials[key]

            return re.sub(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}", replace, value)
        if isinstance(value, dict):
            return {key: cls._render_template(item, credentials) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._render_template(item, credentials) for item in value]
        return value

    @staticmethod
    def _extract_credential(response: httpx.Response, provider: AuthProviderSettings) -> Any:
        spec = provider.extract
        if spec.source == "header":
            return next(
                (value for key, value in response.headers.items() if key.casefold() == spec.path.casefold()),
                None,
            )
        if spec.source == "cookie":
            try:
                return response.cookies.get(spec.path)
            except KeyError:
                return None
        try:
            payload = response.json()
            return read_json_path(payload, spec.path)
        except (ValueError, AssertionEvaluationError, KeyError, IndexError, TypeError):
            return None


def _redis_get(host: str, port: int, password: str, key: str) -> str | None:
    """Read a single SMS verification code from a configured Redis store."""

    def command(*parts: str) -> bytes:
        encoded = [f"*{len(parts)}\r\n".encode()]
        for part in parts:
            value = part.encode()
            encoded.extend([f"${len(value)}\r\n".encode(), value, b"\r\n"])
        return b"".join(encoded)

    with socket.create_connection((host, port), timeout=2.0) as connection:
        if password:
            connection.sendall(command("AUTH", password))
            _read_resp(connection)
        connection.sendall(command("GET", key))
        value = _read_resp(connection)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value) if value is not None else None


def _read_resp(connection: socket.socket) -> Any:
    def read_line() -> bytes:
        data = bytearray()
        while not data.endswith(b"\r\n"):
            chunk = connection.recv(1)
            if not chunk:
                raise ConnectionError("Redis connection closed before a response was received")
            data.extend(chunk)
        return bytes(data[:-2])

    prefix = connection.recv(1)
    if prefix == b"$":
        length = int(read_line())
        if length < 0:
            return None
        data = _recv_exact(connection, length)
        _recv_exact(connection, 2)
        return data
    if prefix in {b"+", b":", b"-"}:
        value = read_line()
        if prefix == b"-":
            raise ConnectionError(value.decode(errors="replace"))
        return int(value) if prefix == b":" else value.decode(errors="replace")
    raise ConnectionError(f"unsupported Redis response: {prefix!r}")


def _recv_exact(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Redis connection closed before the response was complete")
        data.extend(chunk)
    return bytes(data)
