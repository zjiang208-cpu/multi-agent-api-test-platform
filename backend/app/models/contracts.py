from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from app.models.projects import StrictModel

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
ParameterLocation = Literal["path", "query", "header", "cookie"]
OperationConfidence = Literal["confirmed", "inferred", "question"]


class SourceReference(StrictModel):
    """Traceable location of an operation in the original requirement document."""

    source_document_id: str | None = Field(default=None, max_length=200)
    section: str | None = Field(default=None, max_length=500)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    heading: str | None = Field(default=None, max_length=1000)
    source_text: str | None = Field(default=None, max_length=20_000)
    reference: str | None = Field(default=None, max_length=2000)


class OperationParameter(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    location: ParameterLocation
    required: bool = False
    schema_type: str = Field(default="string", alias="type", min_length=1, max_length=40)
    format: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    example: Any | None = None
    enum: list[Any] | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)


class ResponseContract(StrictModel):
    status_code: int = Field(ge=100, le=599)
    description: str = Field(default="", max_length=2000)
    media_type: str | None = Field(default=None, min_length=1, max_length=200)
    schema_definition: dict[str, Any] | None = Field(default=None, alias="schema")
    example: Any | None = None


class OperationContract(StrictModel):
    operation_id: str = Field(min_length=1, max_length=200)
    runtime_session_id: str | None = Field(default=None, min_length=1, max_length=200)
    method: HttpMethod
    path: str = Field(min_length=1, max_length=2000)
    summary: str = Field(default="", max_length=2000)
    parameters: list[OperationParameter] = Field(default_factory=list, max_length=200)
    request_body: dict[str, Any] | None = None
    responses: list[ResponseContract] = Field(min_length=1, max_length=100)
    source_document_id: str | None = Field(default=None, max_length=200)
    source_refs: list[SourceReference] = Field(default_factory=list, max_length=20)
    confidence: OperationConfidence = "inferred"
    contract_metadata: dict[str, Any] = Field(default_factory=dict, max_length=100)

    @field_validator("source_refs", mode="before")
    @classmethod
    def normalize_source_refs(cls, value: Any) -> list[Any]:
        """Accept legacy string refs while storing structured references."""

        if value is None:
            return []
        if isinstance(value, (str, bytes)):
            value = [value]
        return [
            {"reference": item} if isinstance(item, str) else item
            for item in value
        ]

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return str(value).upper()

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("operation path must start with '/'")
        if " " in value or "//" in value:
            raise ValueError("operation path contains unsupported whitespace or '//'")
        if value.count("{") != value.count("}"):
            raise ValueError("operation path has unbalanced path parameters")
        return value

    @property
    def operation_key(self) -> str:
        return f"{self.method} {self.path}"
