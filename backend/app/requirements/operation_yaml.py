from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.core.security import sanitize_text, sanitize_value
from app.models.contracts import OperationContract, OperationParameter, ResponseContract


class OperationYamlLoadError(ValueError):
    pass


class OperationYamlLoader:
    """Load the platform's one-operation-per-YAML contract format."""

    def discover(self, source: str) -> list[OperationContract]:
        path = Path(source).expanduser()
        if not path.is_file():
            raise OperationYamlLoadError(f"operation YAML file not found: {source}")
        try:
            return self.discover_text(path.read_bytes(), source)
        except yaml.YAMLError as exc:
            raise OperationYamlLoadError(f"invalid operation YAML: {exc}") from exc

    def discover_text(self, data: bytes, source: str = "uploaded-operation.yaml") -> list[OperationContract]:
        try:
            raw = yaml.safe_load(data)
        except yaml.YAMLError as exc:
            raise OperationYamlLoadError(f"invalid operation YAML: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("operation"), dict):
            raise OperationYamlLoadError("YAML is not an operation contract")
        return [self._operation(raw, source)]

    def _operation(self, raw: dict[str, Any], source: str) -> OperationContract:
        operation = raw["operation"]
        operation_id = str(operation.get("id") or operation.get("operation_id") or "").strip()
        method = str(operation.get("method") or "").upper()
        path = str(operation.get("path") or "")
        if not operation_id or not method or not path:
            raise OperationYamlLoadError("operation YAML requires id, method and path")

        request = raw.get("request") if isinstance(raw.get("request"), dict) else {}
        parameters = [self._parameter(item) for item in request.get("parameters", []) if isinstance(item, dict)]
        response = raw.get("response") if isinstance(raw.get("response"), dict) else {}
        scenarios = [item for item in response.get("scenarios", []) if isinstance(item, dict)]
        responses = [self._response(item, response.get("envelope")) for item in scenarios]
        if not responses:
            responses = [ResponseContract(status_code=200, description="default response")]

        metadata = {
            "read_only": bool(operation.get("read_only", False)),
            "auth_required": bool(operation.get("auth_required", False)),
            "preconditions": self._strings(raw.get("preconditions")),
            "business_rules": self._strings(raw.get("business_rules")),
            "expected_behaviors": self._expected_behaviors(raw.get("expected_behavior")),
            "unresolved_questions": self._strings(raw.get("unresolved_questions")),
            "scenarios": [
                {
                    "id": str(item.get("id", "")),
                    "condition": str(item.get("condition", "")),
                    "http_status": item.get("http_status"),
                }
                for item in scenarios
            ],
            "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {},
        }
        try:
            return OperationContract(
                operation_id=operation_id,
                method=method,
                path=path,
                summary=sanitize_text(str(operation.get("summary") or ""), max_length=2000),
                parameters=parameters,
                responses=responses,
                source_refs=[source],
                contract_metadata=sanitize_value(metadata),
            )
        except ValidationError as exc:
            raise OperationYamlLoadError(f"operation YAML contract failed validation: {exc}") from exc

    @staticmethod
    def _parameter(value: dict[str, Any]) -> OperationParameter:
        constraints = value.get("constraints", {})
        if isinstance(constraints, list):
            constraints = {"notes": [str(item) for item in constraints]}
        elif not isinstance(constraints, dict):
            constraints = {"value": str(constraints)}
        return OperationParameter(
            name=str(value.get("name", "")),
            location=str(value.get("in", "query")),
            schema_type=str(value.get("type", "string")),
            required=bool(value.get("required", False)),
            example=value.get("example"),
            constraints=constraints,
        )

    @classmethod
    def _response(cls, value: dict[str, Any], envelope: Any) -> ResponseContract:
        status_code = value.get("http_status", 200)
        try:
            status_code = int(status_code)
        except (TypeError, ValueError) as exc:
            raise OperationYamlLoadError(f"invalid scenario HTTP status: {status_code}") from exc
        description = str(value.get("condition") or value.get("id") or "")
        schema = cls._envelope_schema(envelope)
        return ResponseContract(status_code=status_code, description=description, schema=schema)

    @staticmethod
    def _envelope_schema(envelope: Any) -> dict[str, Any] | None:
        if not isinstance(envelope, dict) or not isinstance(envelope.get("fields"), dict):
            return None
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, raw in envelope["fields"].items():
            field = raw if isinstance(raw, dict) else {"type": raw}
            properties[str(name)] = OperationYamlLoader._schema_type(field.get("type"))
            if field.get("required") is True:
                required.append(str(name))
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    @staticmethod
    def _schema_type(value: Any) -> dict[str, Any]:
        name = str(value or "").lower()
        if name == "boolean":
            return {"type": "boolean"}
        if name in {"number", "number_or_null"}:
            schema = {"type": "number"}
        elif name in {"integer", "integer_or_null"}:
            schema = {"type": "integer"}
        elif name in {"object", "object_or_null"}:
            schema = {"type": "object"}
        elif name in {"array", "array_or_null"}:
            schema = {"type": "array"}
        else:
            schema = {"type": "string"}
        if name.endswith("_or_null"):
            return {"anyOf": [schema, {"type": "null"}]}
        return schema

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [sanitize_text(str(item)) for item in value if str(item).strip()]

    @staticmethod
    def _expected_behaviors(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(sanitize_text(str(item.get("description") or item.get("id") or "")))
            else:
                result.append(sanitize_text(str(item)))
        return [item for item in result if item.strip()]
