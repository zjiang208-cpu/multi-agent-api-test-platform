from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from app.models.contracts import OperationContract, OperationParameter, ResponseContract


class SourceLoadError(ValueError):
    pass


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


class OpenApiLoader:
    def __init__(
        self,
        *,
        allow_remote_sources: bool = False,
        max_document_bytes: int = 2_000_000,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.allow_remote_sources = allow_remote_sources
        self.max_document_bytes = max_document_bytes
        self.timeout_seconds = timeout_seconds

    def discover(self, source: str) -> list[OperationContract]:
        raw = self._read_source(source)
        if not raw.get("openapi") and not raw.get("swagger"):
            raise SourceLoadError("source is not an OpenAPI or Swagger document")
        paths = raw.get("paths")
        if not isinstance(paths, dict):
            raise SourceLoadError("OpenAPI document has no paths mapping")

        operations: list[OperationContract] = []
        for path in sorted(paths):
            path_item = paths[path]
            if not isinstance(path_item, dict):
                continue
            path_parameters = path_item.get("parameters", [])
            for method in sorted(HTTP_METHODS.intersection(path_item)):
                operation = path_item[method]
                if not isinstance(operation, dict):
                    continue
                operations.append(
                    self._operation(
                        source=source,
                        path=path,
                        method=method,
                        operation=operation,
                        path_parameters=path_parameters,
                    )
                )
        return operations

    def _read_source(self, source: str) -> dict[str, Any]:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            if not self.allow_remote_sources:
                raise SourceLoadError("remote OpenAPI sources are disabled")
            try:
                with httpx.stream(
                    "GET",
                    source,
                    follow_redirects=False,
                    timeout=self.timeout_seconds,
                ) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length is not None and int(content_length) > self.max_document_bytes:
                        raise SourceLoadError("OpenAPI document exceeds configured size limit")
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_document_bytes:
                            raise SourceLoadError("OpenAPI document exceeds configured size limit")
            except SourceLoadError:
                raise
            except ValueError as exc:
                raise SourceLoadError("invalid OpenAPI response Content-Length") from exc
            except httpx.HTTPError as exc:
                raise SourceLoadError(f"failed to load OpenAPI source: {exc}") from exc
            return self._parse(bytes(content), source)

        path = Path(source).expanduser()
        if not path.is_file():
            raise SourceLoadError(f"OpenAPI source file not found: {source}")
        if path.stat().st_size > self.max_document_bytes:
            raise SourceLoadError("OpenAPI document exceeds configured size limit")
        return self._parse(path.read_bytes(), source)

    @staticmethod
    def _parse(content: bytes, source: str) -> dict[str, Any]:
        try:
            value = json.loads(content) if source.lower().endswith(".json") else yaml.safe_load(content)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise SourceLoadError(f"invalid OpenAPI document: {exc}") from exc
        if not isinstance(value, dict):
            raise SourceLoadError("OpenAPI document root must be a mapping")
        return value

    def _operation(
        self,
        *,
        source: str,
        path: str,
        method: str,
        operation: dict[str, Any],
        path_parameters: Any,
    ) -> OperationContract:
        parameters = self._parameters(path_parameters) + self._parameters(operation.get("parameters", []))
        parameters = self._deduplicate_parameters(parameters)
        operation_id = str(operation.get("operationId") or self._generated_id(method, path))
        responses = self._responses(operation.get("responses", {}))
        if not responses:
            responses = [ResponseContract(status_code=200, description="default response")]
        return OperationContract(
            operation_id=operation_id,
            method=method.upper(),
            path=path,
            summary=str(operation.get("summary") or operation.get("description") or ""),
            parameters=parameters,
            request_body=self._request_body(operation.get("requestBody")),
            responses=responses,
            source_refs=[source],
        )

    @staticmethod
    def _parameters(values: Any) -> list[OperationParameter]:
        if not isinstance(values, list):
            return []
        result: list[OperationParameter] = []
        for value in values:
            if not isinstance(value, dict) or value.get("in") not in {"path", "query", "header", "cookie"}:
                continue
            schema = value.get("schema") or {}
            if not isinstance(schema, dict):
                schema = {}
            result.append(
                OperationParameter(
                    name=str(value.get("name", "")),
                    location=value["in"],
                    required=bool(value.get("required", value["in"] == "path")),
                    type=str(schema.get("type", value.get("type", "string"))),
                    format=schema.get("format", value.get("format")),
                    description=value.get("description"),
                    example=value.get("example", schema.get("example")),
                    enum=schema.get("enum", value.get("enum")),
                    constraints={
                        key: schema[key]
                        for key in ("minimum", "maximum", "minLength", "maxLength", "pattern")
                        if key in schema
                    },
                )
            )
        return result

    @staticmethod
    def _deduplicate_parameters(values: list[OperationParameter]) -> list[OperationParameter]:
        result: list[OperationParameter] = []
        seen: set[tuple[str, str]] = set()
        for value in values:
            key = (value.location, value.name)
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result

    @staticmethod
    def _request_body(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        content = value.get("content")
        if isinstance(content, dict):
            media_type, media_value = next(iter(content.items()), (None, None))
            if isinstance(media_value, dict):
                return {
                    "required": bool(value.get("required", False)),
                    "media_type": media_type,
                    "schema": media_value.get("schema"),
                    "example": media_value.get("example"),
                }
        if "schema" in value:
            return {"required": bool(value.get("required", False)), "schema": value.get("schema")}
        return None

    @staticmethod
    def _responses(values: Any) -> list[ResponseContract]:
        if not isinstance(values, dict):
            return []
        result: list[ResponseContract] = []
        for raw_status in sorted(values, key=str):
            if not str(raw_status).isdigit():
                continue
            value = values[raw_status]
            if not isinstance(value, dict):
                value = {}
            content = value.get("content")
            media_type = None
            schema = None
            example = value.get("example")
            if isinstance(content, dict):
                media_type, media_value = next(iter(content.items()), (None, None))
                if isinstance(media_value, dict):
                    schema = media_value.get("schema")
                    example = media_value.get("example", example)
            result.append(
                ResponseContract(
                    status_code=int(raw_status),
                    description=str(value.get("description", "")),
                    media_type=media_type,
                    schema=schema,
                    example=example,
                )
            )
        return result

    @staticmethod
    def _generated_id(method: str, path: str) -> str:
        value = re.sub(r"[^A-Za-z0-9]+", "-", path.strip("/")).strip("-") or "root"
        return f"{method.lower()}-{value}"
