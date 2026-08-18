from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.security import sanitize_text, sanitize_value

T = TypeVar("T", bound=BaseModel)


ThinkingMode = Literal["enabled", "disabled"]
MAX_REPAIR_OUTPUT_CHARS = 50_000
MAX_VALIDATION_ISSUES = 20


@dataclass(frozen=True)
class ProviderCallInfo:
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None


class ProviderError(RuntimeError):
    """A provider failure with bounded diagnostics safe for durable telemetry.

    ``repair_payload`` is deliberately memory-only. It may be sent back to the
    same provider for a schema-repair attempt, but must never be persisted in
    workflow metadata or exposed by the API.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        retryable: bool = True,
        repair_payload: Any | None = None,
        validation_issues: tuple[str, ...] = (),
        output_chars: int = 0,
        call_info: ProviderCallInfo | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.repair_payload = repair_payload
        self.validation_issues = validation_issues[:MAX_VALIDATION_ISSUES]
        self.output_chars = max(0, output_chars)
        self.call_info = call_info or ProviderCallInfo()


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

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        thinking_mode: ThinkingMode = "enabled",
    ) -> T:
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
            # Models sometimes wrap an otherwise valid object in a sentence,
            # Markdown, or trailing commentary.  Decode the first complete
            # JSON value rather than requiring the entire response to be JSON.
            decoder = json.JSONDecoder()
            starts = [index for index, char in enumerate(text) if char in "{["]
            value = None
            for start in starts:
                try:
                    value, _ = decoder.raw_decode(text[start:])
                    break
                except json.JSONDecodeError:
                    continue
            if value is None:
                repair_payload = sanitize_text(text, max_length=MAX_REPAIR_OUTPUT_CHARS)
                raise ProviderError(
                    "provider did not return JSON",
                    category="non_json",
                    repair_payload=repair_payload or None,
                    output_chars=len(raw),
                ) from exc
        try:
            return response_model.model_validate(value)
        except ValidationError as exc:
            issues = tuple(
                f"{StructuredOutputParser._format_location(error.get('loc', ()))}: "
                f"{error.get('type', 'validation_error')}"
                for error in exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )[:MAX_VALIDATION_ISSUES]
            )
            repair_payload = sanitize_value(value)
            if len(json.dumps(repair_payload, ensure_ascii=False, default=str)) > MAX_REPAIR_OUTPUT_CHARS:
                repair_payload = None
            raise ProviderError(
                "provider output failed schema validation",
                category="schema_validation",
                repair_payload=repair_payload,
                validation_issues=issues,
                output_chars=len(raw),
            ) from exc

    @staticmethod
    def _format_location(location: tuple[Any, ...]) -> str:
        if not location:
            return "$"
        rendered = "$"
        for part in location:
            if isinstance(part, int):
                rendered += f"[{part}]"
            else:
                rendered += f".{part}"
        return rendered


class FakeLlmProvider:
    provider_name = "fake"

    def __init__(self, response_factory):
        self.response_factory = response_factory
        self.calls: list[dict[str, str]] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        thinking_mode: ThinkingMode = "enabled",
    ) -> T:
        self.calls.append(
            {"system": system, "user": user, "thinking_mode": thinking_mode}
        )
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
        # DeepSeek V4 may spend most of the completion budget on reasoning
        # before emitting the JSON body. Keep enough headroom for both.
        max_tokens: int = 32_768,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_ref = api_key_ref
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.last_call_info = ProviderCallInfo()

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        thinking_mode: ThinkingMode = "enabled",
    ) -> T:
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
            "thinking": {"type": thinking_mode},
            "max_tokens": self.max_tokens,
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
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
            usage = data.get("usage") or {}
            completion_details = usage.get("completion_tokens_details") or {}
            call_info = ProviderCallInfo(
                finish_reason=choice.get("finish_reason"),
                prompt_tokens=_optional_int(usage.get("prompt_tokens")),
                completion_tokens=_optional_int(usage.get("completion_tokens")),
                reasoning_tokens=_optional_int(completion_details.get("reasoning_tokens")),
            )
            self.last_call_info = call_info
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "LLM provider request failed: TimeoutException",
                category="timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            category = "http_5xx" if status_code >= 500 else "http_4xx"
            raise ProviderError(
                "LLM provider request failed: HTTPStatusError",
                category=category,
                retryable=status_code >= 500 or status_code == 429,
            ) from exc
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"LLM provider request failed: {type(exc).__name__}",
                category="invalid_provider_response",
            ) from exc

        raw_content = "" if content is None else str(content)
        if call_info.finish_reason == "length":
            raise ProviderError(
                "provider output was truncated",
                category="output_truncated",
                output_chars=len(raw_content),
                call_info=call_info,
            )
        if call_info.finish_reason == "content_filter":
            raise ProviderError(
                "provider output was blocked by content filter",
                category="content_filter",
                retryable=False,
                output_chars=len(raw_content),
                call_info=call_info,
            )
        if not raw_content.strip():
            raise ProviderError(
                "provider returned empty content",
                category="empty_response",
                output_chars=0,
                call_info=call_info,
            )
        try:
            return StructuredOutputParser.parse(raw_content, response_model)
        except ProviderError as exc:
            exc.call_info = call_info
            raise


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
