from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Generic, TypeVar

from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from app.core.security import is_sensitive_key, sanitize_text
from app.providers.llm import CallBudget, LlmProvider, ProviderError, StructuredOutputParser

T = TypeVar("T", bound=BaseModel)
MAX_PROMPT_TEXT = 50_000


@dataclass(frozen=True)
class LlmCallMetric:
    stage: str
    attempt: int
    duration_ms: int
    input_chars: int
    output_chars: int
    status: str


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
) -> StructuredLangChainAgent[T]:
    """Adapt the existing provider-neutral client into a LangChain Runnable."""

    schema_chars = len(
        json.dumps(response_model.model_json_schema(), ensure_ascii=False, default=str)
    )

    def call(payload: dict[str, Any]) -> T:
        user_prompt = json.dumps(_safe_jsonable(payload), ensure_ascii=False, default=str)
        last_error: ProviderError | None = None
        for attempt in range(max_attempts):
            if budget is not None:
                budget.consume()
            retry_prompt = user_prompt
            if attempt:
                retry_prompt += (
                    "\n\nThe previous response was invalid. Return one JSON object that strictly "
                    "matches the supplied schema; do not add Markdown or commentary."
                )
            started = perf_counter()
            try:
                result = provider.complete(
                    system=system_prompt,
                    user=retry_prompt,
                    response_model=response_model,
                )
            except ProviderError as exc:
                if telemetry is not None:
                    telemetry.record(
                        LlmCallMetric(
                            stage=stage,
                            attempt=attempt + 1,
                            duration_ms=round((perf_counter() - started) * 1000),
                            input_chars=len(system_prompt) + len(retry_prompt) + schema_chars,
                            output_chars=0,
                            status="error",
                        )
                    )
                last_error = exc
                continue
            if telemetry is not None:
                output = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
                telemetry.record(
                    LlmCallMetric(
                        stage=stage,
                        attempt=attempt + 1,
                        duration_ms=round((perf_counter() - started) * 1000),
                        input_chars=len(system_prompt) + len(retry_prompt) + schema_chars,
                        output_chars=len(json.dumps(output, ensure_ascii=False, default=str)),
                        status="success",
                    )
                )
            return result
        assert last_error is not None
        raise last_error

    return StructuredLangChainAgent(RunnableLambda(call), response_model, telemetry=telemetry)


def _safe_jsonable(value: Any) -> Any:
    """Create a bounded, display-safe JSON payload for an LLM request."""

    if isinstance(value, BaseModel):
        return _safe_jsonable(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if is_sensitive_key(str(key)) else _safe_jsonable(item)
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
