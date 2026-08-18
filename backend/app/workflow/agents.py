from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Generic, TypeVar

from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from app.core.security import SAFE_FIXTURE_VALUE, is_sensitive_key, sanitize_text
from app.providers.llm import (
    CallBudget,
    LlmProvider,
    ProviderCallInfo,
    ProviderError,
    StructuredOutputParser,
    ThinkingMode,
)

T = TypeVar("T", bound=BaseModel)
MAX_PROMPT_TEXT = 50_000
REPAIR_SYSTEM_PROMPT = """You repair an already-designed structured JSON result.
Do not redesign the test cases, change business meaning, add speculative coverage, or
remove supported cases. Correct only the listed structural validation errors using the
original input as reference. Return exactly one JSON object matching the supplied schema,
without Markdown or commentary."""


@dataclass(frozen=True)
class LlmCallMetric:
    stage: str
    attempt: int
    duration_ms: int
    input_chars: int
    output_chars: int
    status: str
    mode: str = "generate"
    error_category: str | None = None
    validation_issues: tuple[str, ...] = ()
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass
class LlmTelemetry:
    records: list[LlmCallMetric] = field(default_factory=list)

    def record(self, metric: LlmCallMetric) -> None:
        self.records.append(metric)

    def metadata(self) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for stage in sorted({record.stage for record in self.records}):
            records = [record for record in self.records if record.stage == stage]
            metadata[f"llm_{stage}_calls"] = str(len(records))
            metadata[f"llm_{stage}_duration_ms"] = str(sum(record.duration_ms for record in records))
            metadata[f"llm_{stage}_input_chars"] = str(sum(record.input_chars for record in records))
            metadata[f"llm_{stage}_output_chars"] = str(sum(record.output_chars for record in records))
            for call_index, record in enumerate(records, 1):
                prefix = f"llm_{stage}_call_{call_index}"
                metadata[f"{prefix}_attempt"] = str(record.attempt)
                metadata[f"{prefix}_mode"] = record.mode
                metadata[f"{prefix}_status"] = record.status
                if record.error_category:
                    metadata[f"{prefix}_error_category"] = record.error_category
                if record.validation_issues:
                    metadata[f"{prefix}_validation_issues"] = " | ".join(
                        record.validation_issues[:10]
                    )[:2000]
                if record.finish_reason:
                    metadata[f"{prefix}_finish_reason"] = record.finish_reason
                for metric_name in (
                    "prompt_tokens",
                    "completion_tokens",
                    "reasoning_tokens",
                ):
                    value = getattr(record, metric_name)
                    if value is not None:
                        metadata[f"{prefix}_{metric_name}"] = str(value)
        return metadata


class StructuredLangChainAgent(Generic[T]):
    """A LangChain Runnable boundary with a strict Pydantic output contract."""

    def __init__(
        self,
        runnable: Runnable[Any, Any],
        response_model: type[T],
        *,
        telemetry: LlmTelemetry | None = None,
    ) -> None:
        self.runnable = runnable
        self.response_model = response_model
        self.telemetry = telemetry
        self.last_metrics: list[LlmCallMetric] = []

    def invoke(self, payload: dict[str, Any]) -> T:
        start_index = len(self.telemetry.records) if self.telemetry else 0
        try:
            result = self.runnable.invoke(payload)
        finally:
            self.last_metrics = self.telemetry.records[start_index:] if self.telemetry else []
        if isinstance(result, self.response_model):
            return result
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json")
        if isinstance(result, str):
            return StructuredOutputParser.parse(result, self.response_model)
        return self.response_model.model_validate(result)


def provider_agent(
    provider: LlmProvider,
    *,
    system_prompt: str,
    response_model: type[T],
    budget: CallBudget | None = None,
    max_attempts: int = 1,
    telemetry: LlmTelemetry | None = None,
    stage: str = "workflow",
    thinking_mode: ThinkingMode = "enabled",
    repair_thinking_mode: ThinkingMode = "disabled",
) -> StructuredLangChainAgent[T]:
    """Adapt the existing provider-neutral client into a LangChain Runnable."""

    schema_chars = len(
        json.dumps(response_model.model_json_schema(), ensure_ascii=False, default=str)
    )

    def call(payload: dict[str, Any]) -> T:
        safe_payload = _safe_jsonable(payload)
        user_prompt = json.dumps(safe_payload, ensure_ascii=False, default=str)
        last_error: ProviderError | None = None
        for attempt in range(max_attempts):
            if budget is not None:
                budget.consume()
            repair_mode = bool(last_error and last_error.repair_payload is not None)
            empty_response_retry = bool(
                last_error and last_error.category == "empty_response" and not repair_mode
            )
            call_mode = "repair" if repair_mode else "regenerate" if empty_response_retry else "generate"
            call_system = REPAIR_SYSTEM_PROMPT if repair_mode else system_prompt
            call_prompt = (
                _repair_prompt(last_error, safe_payload)
                if repair_mode and last_error is not None
                else _regeneration_prompt(user_prompt, last_error)
            )
            call_thinking_mode = (
                repair_thinking_mode
                if repair_mode or empty_response_retry
                else thinking_mode
            )
            started = perf_counter()
            try:
                result = provider.complete(
                    system=call_system,
                    user=call_prompt,
                    response_model=response_model,
                    thinking_mode=call_thinking_mode,
                )
            except ProviderError as exc:
                call_info = exc.call_info
                if telemetry is not None:
                    telemetry.record(
                        LlmCallMetric(
                            stage=stage,
                            attempt=attempt + 1,
                            duration_ms=round((perf_counter() - started) * 1000),
                            input_chars=len(call_system) + len(call_prompt) + schema_chars,
                            output_chars=exc.output_chars,
                            status="error",
                            mode=call_mode,
                            error_category=exc.category,
                            validation_issues=exc.validation_issues,
                            **_call_info_fields(call_info),
                        )
                    )
                last_error = exc
                if not exc.retryable:
                    break
                continue
            if telemetry is not None:
                output = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
                call_info = getattr(provider, "last_call_info", ProviderCallInfo())
                telemetry.record(
                    LlmCallMetric(
                        stage=stage,
                        attempt=attempt + 1,
                        duration_ms=round((perf_counter() - started) * 1000),
                        input_chars=len(call_system) + len(call_prompt) + schema_chars,
                        output_chars=len(json.dumps(output, ensure_ascii=False, default=str)),
                        status="success",
                        mode=call_mode,
                        **_call_info_fields(call_info),
                    )
                )
            return result
        assert last_error is not None
        raise last_error

    return StructuredLangChainAgent(RunnableLambda(call), response_model, telemetry=telemetry)


def _repair_prompt(error: ProviderError, original_input: Any) -> str:
    return json.dumps(
        {
            "task": "repair_structured_output",
            "instructions": [
                "Preserve the completed business reasoning and test intent.",
                "Fix only JSON structure, required fields, types, and allowed values.",
                "Use original_input only to restore information omitted from previous_output.",
                "Do not add unsupported cases, assertions, evidence, or request values.",
                "Return the corrected JSON object only.",
            ],
            "validation_errors": list(error.validation_issues)
            or [error.category],
            "previous_output": error.repair_payload,
            "original_input": original_input,
        },
        ensure_ascii=False,
        default=str,
    )


def _regeneration_prompt(user_prompt: str, error: ProviderError | None) -> str:
    if error is None:
        return user_prompt
    hints = {
        "output_truncated": "The previous response was truncated. Return a concise complete JSON object.",
        "empty_response": "The previous response was empty. Return exactly one complete JSON object.",
        "timeout": "The previous provider request timed out. Complete the original task once.",
        "http_5xx": "The previous provider request failed temporarily. Complete the original task once.",
        "invalid_provider_response": "The previous provider response was malformed. Return exactly one JSON object.",
    }
    hint = hints.get(error.category, "Complete the original task and return exactly one JSON object.")
    return f"{user_prompt}\n\n{hint}"


def _call_info_fields(call_info: ProviderCallInfo) -> dict[str, Any]:
    return {
        "finish_reason": call_info.finish_reason,
        "prompt_tokens": call_info.prompt_tokens,
        "completion_tokens": call_info.completion_tokens,
        "reasoning_tokens": call_info.reasoning_tokens,
    }


def _safe_jsonable(value: Any) -> Any:
    """Create a bounded, display-safe JSON payload for an LLM request."""

    if isinstance(value, BaseModel):
        return _safe_jsonable(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, Mapping):
        return {
            str(key): (
                item
                if is_sensitive_key(str(key))
                and isinstance(item, str)
                and SAFE_FIXTURE_VALUE.fullmatch(item.strip())
                else "<redacted>"
                if is_sensitive_key(str(key))
                else _safe_jsonable(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_jsonable(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, max_length=MAX_PROMPT_TEXT)
    return value


def fake_agent(
    response_model: type[T],
    factory,
) -> StructuredLangChainAgent[T]:
    """Build a deterministic LangChain agent for unit and contract tests."""

    return StructuredLangChainAgent(RunnableLambda(factory), response_model)
