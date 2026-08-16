from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class TargetSettings(StrictModel):
    base_url: AnyHttpUrl
    timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    allow_redirects: bool = False
    verify_tls: bool = True
    auth_ref: str | None = Field(default=None, min_length=1, max_length=200)


class AuthRequestSpec(StrictModel):
    """Deterministic login request used by a configurable Auth Provider."""

    method: str = Field(default="POST", min_length=1, max_length=12)
    path: str = Field(min_length=1, max_length=1000)
    body_type: Literal["json", "form", "none"] = "json"
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None
    credential_refs: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("credential_refs")
    @classmethod
    def validate_credential_refs(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not reference.startswith("env:") for reference in values.values()):
            raise ValueError("Auth Provider credentials must use env:NAME references")
        return values

    @field_validator("body", "headers")
    @classmethod
    def reject_inline_secrets(cls, value: Any) -> Any:
        sensitive_names = {
            "password",
            "passwd",
            "secret",
            "client_secret",
            "api_key",
            "access_token",
            "refresh_token",
            "token",
            "authorization",
        }

        def visit(item: Any, key: str = "") -> None:
            if isinstance(item, dict):
                for child_key, child_value in item.items():
                    visit(child_value, str(child_key).casefold().replace("-", "_"))
            elif isinstance(item, list):
                for child_value in item:
                    visit(child_value, key)
            elif key in sensitive_names and not (isinstance(item, str) and "{{" in item):
                raise ValueError(
                    "Auth Provider secrets must use {{name}} templates and credential_refs"
                )

        visit(value)
        return value


class AuthExtractSpec(StrictModel):
    """Where a login response exposes the credential."""

    source: Literal["json", "header", "cookie"] = "json"
    path: str = Field(default="$.data", min_length=1, max_length=500)


class AuthInjectSpec(StrictModel):
    """How the credential is added to subsequent test requests."""

    location: Literal["header", "cookie"] = "header"
    name: str = Field(default="Authorization", min_length=1, max_length=200)
    prefix: str | None = Field(default="Bearer", max_length=80)


class AuthNegativeFixtureSettings(StrictModel):
    """Optional deterministic fixtures for authentication negative cases."""

    expired_token_ref: str | None = Field(default=None, max_length=200)

    @field_validator("expired_token_ref")
    @classmethod
    def validate_expired_token_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("env:"):
            raise ValueError("expired Token fixtures must use env:NAME references")
        return value


def _default_sms_code_request() -> AuthRequestSpec:
    return AuthRequestSpec(
        method="POST",
        path="/auth/sms/code",
        query_params={"phone": "{{phone}}"},
        body_type="none",
    )


def _default_sms_login_request() -> AuthRequestSpec:
    return AuthRequestSpec(
        method="POST",
        path="/auth/sms/login",
        body_type="json",
        body={"phone": "{{phone}}", "code": "{{code}}"},
    )


class SmsAuthSettings(StrictModel):
    """Portable SMS verification flow configuration."""

    phone_ref: str = Field(default="env:TEST_LOGIN_PHONE", min_length=1, max_length=200)
    code_request: AuthRequestSpec = Field(default_factory=_default_sms_code_request)
    code_source: Literal["redis", "json"] = "redis"
    code_path: str = Field(default="login:code:{{phone}}", min_length=1, max_length=500)
    redis_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    # Most local Redis instances have no password; configure env:NAME only
    # when the target Redis requires authentication.
    redis_password_ref: str | None = Field(default=None, max_length=200)
    login: AuthRequestSpec = Field(default_factory=_default_sms_login_request)

    @field_validator("phone_ref", "redis_password_ref")
    @classmethod
    def validate_secret_refs(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("env:"):
            raise ValueError("SMS credentials must use env:NAME references")
        return value


class AuthProviderSettings(StrictModel):
    """Project-level authentication provider configuration.

    ``http`` is the portable provider: it works with any HTTP service and
    requires only a login request, response extraction rule, and injection rule.
    """

    enabled: bool = False
    kind: Literal["http", "sms"] = "http"
    token_ttl_seconds: int | None = Field(default=1800, gt=0, le=604800)
    login: AuthRequestSpec | None = None
    extract: AuthExtractSpec = Field(default_factory=AuthExtractSpec)
    inject: AuthInjectSpec = Field(default_factory=AuthInjectSpec)
    negative_fixtures: AuthNegativeFixtureSettings = Field(
        default_factory=AuthNegativeFixtureSettings
    )
    sms: SmsAuthSettings = Field(default_factory=SmsAuthSettings)

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_legacy_kind(cls, value: Any) -> str:
        # Older local settings may contain a project-specific SMS kind. Treat
        # any non-HTTP legacy value as the portable SMS adapter without keeping
        # that project name in the public contract.
        return "http" if value == "http" else "sms"


class AuthRefreshResponse(StrictModel):
    """Safe result returned after an explicit authentication preflight."""

    success: bool
    status: Literal["refreshed", "disabled", "reference", "failed"]
    message: str


class DatabaseProfile(StrictModel):
    enabled: bool = False
    dialect: str | None = Field(default=None, min_length=1, max_length=40)
    dsn_ref: str | None = Field(default=None, min_length=1, max_length=200)
    readonly: Literal[True] = True
    schema_name: str | None = Field(
        default=None,
        alias="schema",
        min_length=1,
        max_length=128,
    )
    allowed_tables: list[str] = Field(default_factory=list, max_length=200)


class LlmProfile(StrictModel):
    enabled: bool = False
    provider: str = Field(default="openai_compatible", min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=160)
    api_key_ref: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: AnyHttpUrl | None = None
    call_budget: int = Field(default=20, ge=1, le=1000)


class ProjectSettings(StrictModel):
    # Deprecated compatibility field. Requirement documents are parsed by the
    # standalone document-ingestion API and are not project configuration.
    requirement_sources: list[str] = Field(default_factory=list, max_length=50)
    openapi_sources: list[str] = Field(default_factory=list, max_length=50)
    source_workspace: str | None = Field(default=None, min_length=1, max_length=1000)
    sut_target: TargetSettings
    auth_provider: AuthProviderSettings = Field(default_factory=AuthProviderSettings)
    database: DatabaseProfile = Field(default_factory=DatabaseProfile)
    llm: LlmProfile = Field(default_factory=LlmProfile)

    @field_validator("requirement_sources", "openapi_sources")
    @classmethod
    def validate_sources(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("source references must not be empty")
        return cleaned


class TestProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    settings: ProjectSettings


class TestProjectUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    settings: ProjectSettings | None = None


class TestProject(StrictModel):
    project_id: str
    name: str
    description: str
    settings: ProjectSettings
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, request: TestProjectCreate) -> "TestProject":
        now = utc_now()
        return cls(
            project_id=f"project-{uuid4().hex}",
            name=request.name,
            description=request.description,
            settings=request.settings,
            created_at=now,
            updated_at=now,
        )
