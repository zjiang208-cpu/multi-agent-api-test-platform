from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    pass


class SecretReferenceError(ProviderError):
    pass


def resolve_secret_reference(reference: str | None) -> str:
    if not reference or not reference.startswith("env:"):
        raise SecretReferenceError("LLM credentials must use an env:NAME reference")
    name = reference[4:]
    if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
        raise SecretReferenceError("invalid environment secret reference")
    value = os.getenv(name)
    if not value:
        raise SecretReferenceError("referenced LLM credential is not configured")
    return value


class LlmProvider(Protocol):
    provider_name: str

    def complete(self, *, system: str, user: str, response_model: type[T]) -> T:
        ...


@dataclass
class CallBudget:
    max_calls: int = 20
    calls: int = 0

    def consume(self) -> None:
        if self.calls >= self.max_calls:
            raise ProviderError("LLM call budget exceeded")
        self.calls += 1


class StructuredOutputParser:
    @staticmethod
    def parse(raw: str, response_model: type[T]) -> T:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.strip().startswith("```"))
        try:
            value: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            start = min(index for index in (text.find("{"), text.find("[")) if index >= 0) if ("{" in text or "[" in text) else -1
            if start < 0:
                raise ProviderError(f"provider did not return JSON: {exc}") from exc
            try:
                value = json.loads(text[start:])
            except json.JSONDecodeError as nested:
                raise ProviderError(f"provider returned invalid JSON: {nested}") from nested
        try:
            return response_model.model_validate(value)
        except ValidationError as exc:
            raise ProviderError(f"provider output failed schema validation: {exc}") from exc


class FakeLlmProvider:
    provider_name = "fake"

    def __init__(self, response_factory):
        self.response_factory = response_factory
        self.calls: list[dict[str, str]] = []

    def complete(self, *, system: str, user: str, response_model: type[T]) -> T:
        self.calls.append({"system": system, "user": user})
        value = self.response_factory(response_model)
        if isinstance(value, response_model):
            return value
        return response_model.model_validate(value)


class OpenAICompatibleProvider:
    """Minimal provider-neutral adapter for OpenAI-compatible chat endpoints."""

    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_ref: str,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_ref = api_key_ref
        self.timeout_seconds = timeout_seconds

    def complete(self, *, system: str, user: str, response_model: type[T]) -> T:
        api_key = resolve_secret_reference(self.api_key_ref)
        schema = response_model.model_json_schema()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        payload["messages"][0]["content"] += "\nReturn JSON matching this schema:\n" + json.dumps(schema)
        try:
            response = httpx.post(
                self.base_url + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise ProviderError(f"LLM provider request failed: {type(exc).__name__}") from exc
        return StructuredOutputParser.parse(str(content), response_model)
