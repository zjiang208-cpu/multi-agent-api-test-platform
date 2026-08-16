from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.executor.auth import AutomaticAuthenticationError, AutomaticAuthProvider, AuthCredentials
from app.executor.http import HttpExecutor
from app.models.cases import TestCase
from app.models.projects import AuthNegativeFixtureSettings, ProjectSettings


def _settings() -> ProjectSettings:
    return ProjectSettings.model_validate(
        {
            "sut_target": {"base_url": "http://127.0.0.1:8081"},
            "auth_provider": {
                "enabled": True,
                "kind": "http",
                "login": {
                    "method": "POST",
                    "path": "/auth/login",
                    "body": {"username": "{{username}}", "password": "{{password}}"},
                    "credential_refs": {
                        "username": "env:TEST_AUTH_USER",
                        "password": "env:TEST_AUTH_PASSWORD",
                    },
                },
                "extract": {"source": "json", "path": "$.data.access_token"},
                "inject": {"location": "header", "name": "X-Auth-Token", "prefix": None},
            },
        }
    )


def _case() -> TestCase:
    return TestCase.model_validate(
        {
            "case_id": "case-auth",
            "requirement_id": "requirement-auth",
            "title": "protected endpoint",
            "category": "positive",
            "preconditions": ["caller is logged in"],
            "steps": ["call endpoint"],
            "expected_behavior": "request succeeds",
            "request": {"method": "GET", "path": "/protected"},
            "assertions": [{"assertion_id": "assert-status", "type": "status_code", "expected": 200}],
        }
    )


def test_configured_auth_provider_extracts_and_renders_credentials(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_USER", "alice")
    monkeypatch.setenv("TEST_AUTH_PASSWORD", "secret")

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, **kwargs):
            assert kwargs["json"] == {"username": "alice", "password": "secret"}
            return httpx.Response(200, json={"data": {"access_token": "token-1"}})

    with patch("app.executor.auth.httpx.AsyncClient", Client):
        credentials = asyncio.run(
            AutomaticAuthProvider().resolve(
                _settings(),
                project_id="project-auth",
                base_url="http://127.0.0.1:8081",
                cases=[_case()],
            )
        )

    assert credentials is not None
    assert credentials.token == "token-1"
    assert credentials.name == "X-Auth-Token"
    assert credentials.prefix is None


def test_sms_auth_provider_requests_code_and_logs_in(monkeypatch):
    monkeypatch.setenv("TEST_LOGIN_PHONE", "13800000000")
    settings = ProjectSettings.model_validate(
        {
            "sut_target": {"base_url": "http://127.0.0.1:8081"},
            "auth_provider": {
                "enabled": True,
                "kind": "sms",
                "sms": {
                    "phone_ref": "env:TEST_LOGIN_PHONE",
                    "code_request": {
                        "method": "POST",
                        "path": "/auth/sms/code",
                        "query_params": {"phone": "{{phone}}"},
                        "body_type": "none",
                    },
                    "code_source": "json",
                    "code_path": "$.data.code",
                    "login": {
                        "method": "POST",
                        "path": "/auth/sms/login",
                        "body": {"phone": "{{phone}}", "code": "{{code}}"},
                    },
                },
                "extract": {"source": "json", "path": "$.data.token"},
                "inject": {"location": "header", "name": "Authorization", "prefix": "Bearer"},
            },
        }
    )

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, **kwargs):
            if kwargs["url"].endswith("/auth/sms/code"):
                assert kwargs["params"] == {"phone": "13800000000"}
                return httpx.Response(200, json={"data": {"code": "123456"}})
            assert kwargs["json"] == {"phone": "13800000000", "code": "123456"}
            return httpx.Response(200, json={"data": {"token": "token-sms"}})

    with patch("app.executor.auth.httpx.AsyncClient", Client):
        credentials = asyncio.run(
            AutomaticAuthProvider().resolve(
                settings,
                project_id="project-sms",
                base_url="http://127.0.0.1:8081",
                cases=[_case()],
            )
        )

    assert credentials is not None
    assert credentials.token == "token-sms"
    assert credentials.prefix == "Bearer"


def test_configured_auth_provider_can_refresh_after_token_rejection(monkeypatch):
    from app.executor.auth import AuthCredentials

    settings = _settings()
    provider = AutomaticAuthProvider()
    issued: list[str] = []

    async def fake_login(*_args, **_kwargs):
        token = f"token-{len(issued) + 1}"
        issued.append(token)
        return AuthCredentials(token=token)

    monkeypatch.setattr(provider, "_resolve_configured_http", fake_login)

    first = asyncio.run(provider.resolve(settings, project_id="project-auth", base_url="http://127.0.0.1:8081", cases=[_case()]))
    cached = asyncio.run(provider.resolve(settings, project_id="project-auth", base_url="http://127.0.0.1:8081", cases=[_case()]))
    provider.invalidate("project-auth", "http://127.0.0.1:8081")
    refreshed = asyncio.run(provider.resolve(settings, project_id="project-auth", base_url="http://127.0.0.1:8081", cases=[_case()]))

    assert first is not None and cached is not None and refreshed is not None
    assert [first.token, cached.token, refreshed.token] == ["token-1", "token-1", "token-2"]


def test_configured_auth_provider_refreshes_after_ttl(monkeypatch):
    from app.executor.auth import AuthCredentials

    settings = _settings().model_copy(
        update={
            "auth_provider": _settings().auth_provider.model_copy(
                update={"token_ttl_seconds": 1}
            )
        }
    )
    provider = AutomaticAuthProvider()
    issued: list[str] = []

    async def fake_login(*_args, **_kwargs):
        token = f"token-{len(issued) + 1}"
        issued.append(token)
        return AuthCredentials(token=token)

    monkeypatch.setattr(provider, "_resolve_configured_http", fake_login)
    with patch.object(AutomaticAuthProvider, "_expires_at", return_value=0.0):
        first = asyncio.run(provider.resolve(settings, project_id="project-auth", base_url="http://127.0.0.1:8081", cases=[_case()]))
        refreshed = asyncio.run(provider.resolve(settings, project_id="project-auth", base_url="http://127.0.0.1:8081", cases=[_case()]))

    assert first is not None and refreshed is not None
    assert [first.token, refreshed.token] == ["token-1", "token-2"]


def test_auth_cache_is_isolated_between_projects_with_the_same_base_url():
    provider = AutomaticAuthProvider()
    provider._resolve_configured_http = AsyncMock(
        side_effect=[AuthCredentials(token="token-a"), AuthCredentials(token="token-b")]
    )

    first = asyncio.run(
        provider.resolve(
            _settings(),
            project_id="project-a",
            base_url="http://127.0.0.1:8081",
            cases=[_case()],
        )
    )
    second = asyncio.run(
        provider.resolve(
            _settings(),
            project_id="project-b",
            base_url="http://127.0.0.1:8081",
            cases=[_case()],
        )
    )

    assert first is not None and second is not None
    assert [first.token, second.token] == ["token-a", "token-b"]
    assert provider._resolve_configured_http.await_count == 2


def test_auth_provider_rejects_remote_login_when_remote_targets_are_disabled():
    provider = AutomaticAuthProvider(allow_remote_targets=False)

    with pytest.raises(AutomaticAuthenticationError, match="remote targets are disabled"):
        asyncio.run(
            provider.resolve(
                _settings(),
                project_id="project-auth",
                base_url="https://example.com",
                cases=[_case()],
            )
        )


def test_http_executor_injects_cookie_credentials():
    case = _case().model_copy(
        update={
            "request": _case().request.model_copy(
                update={"headers": {"Cookie": "theme=dark; session=old"}}
            )
        }
    )
    seen: list[str | None] = []
    transport = httpx.MockTransport(
        lambda request: (
            seen.append(request.headers.get("cookie"))
            or httpx.Response(200, json={"ok": True}, request=request)
        )
    )
    result = asyncio.run(
        HttpExecutor(
            transport=transport,
            auth_token="session-new",
            auth_location="cookie",
            auth_name="session",
        ).execute(case, _settings())
    )

    assert result.status == "passed"
    assert seen == ["theme=dark; session=session-new"]


def test_http_executor_replaces_stale_case_auth_header():
    case = _case().model_copy(
        update={
            "request": _case().request.model_copy(
                update={"headers": {"Authorization": "Bearer test-token"}}
            )
        }
    )
    seen: list[str | None] = []
    transport = httpx.MockTransport(
        lambda request: (
            seen.append(request.headers.get("authorization"))
            or httpx.Response(200, json={"ok": True}, request=request)
        )
    )

    result = asyncio.run(
        HttpExecutor(
            transport=transport,
            auth_token="token-live",
            auth_prefix=None,
            auth_name="Authorization",
        ).execute(case, _settings())
    )

    assert result.status == "passed"
    assert seen == ["token-live"]


def test_http_executor_preserves_explicit_unauthorized_case():
    source_case = _case()
    case = source_case.model_copy(
        update={
            "request": source_case.request.model_copy(
                update={"headers": {"Authorization": "Bearer invalid-token"}}
            ),
            "assertions": [source_case.assertions[0].model_copy(update={"assertion_id": "assert-unauthorized", "expected": 401})],
        }
    )
    seen: list[str | None] = []
    transport = httpx.MockTransport(
        lambda request: (
            seen.append(request.headers.get("authorization"))
            or httpx.Response(401, request=request)
        )
    )

    result = asyncio.run(
        HttpExecutor(
            transport=transport,
            auth_token="token-live",
            auth_prefix=None,
            auth_name="Authorization",
        ).execute(case, _settings())
    )

    assert result.status == "passed"
    assert seen == ["Bearer invalid-token"]


def test_http_executor_resolves_nonexistent_auth_fixture_for_negative_case():
    source_case = _case()
    case = source_case.model_copy(
        update={
            "request": source_case.request.model_copy(
                update={"headers": {"Authorization": "$AUTH_FIXTURE[nonexistent:token]"}}
            ),
            "assertions": [
                source_case.assertions[0].model_copy(
                    update={"assertion_id": "assert-unauthorized", "expected": 401}
                )
            ],
        }
    )
    seen: list[str | None] = []
    transport = httpx.MockTransport(
        lambda request: (
            seen.append(request.headers.get("authorization"))
            or httpx.Response(401, request=request)
        )
    )

    result = asyncio.run(HttpExecutor(transport=transport).execute(case, _settings()))

    assert result.status == "passed"
    assert seen[0] is not None
    assert seen[0].startswith("__api_test_nonexistent_token_")
    assert "$AUTH_FIXTURE" not in seen[0]


def test_http_executor_resolves_configured_expired_auth_fixture(monkeypatch):
    monkeypatch.setenv("TEST_EXPIRED_TOKEN", "expired-token-fixture")
    settings = _settings().model_copy(
        update={
            "auth_provider": _settings().auth_provider.model_copy(
                update={
                    "negative_fixtures": AuthNegativeFixtureSettings(
                        expired_token_ref="env:TEST_EXPIRED_TOKEN"
                    )
                }
            )
        }
    )
    source_case = _case()
    case = source_case.model_copy(
        update={
            "request": source_case.request.model_copy(
                update={"headers": {"Authorization": "$AUTH_FIXTURE[expired:token]"}}
            ),
            "assertions": [
                source_case.assertions[0].model_copy(
                    update={"assertion_id": "assert-unauthorized", "expected": 401}
                )
            ],
        }
    )
    seen: list[str | None] = []
    transport = httpx.MockTransport(
        lambda request: (
            seen.append(request.headers.get("authorization"))
            or httpx.Response(401, request=request)
        )
    )

    result = asyncio.run(HttpExecutor(transport=transport).execute(case, settings))

    assert result.status == "passed"
    assert seen == ["expired-token-fixture"]
