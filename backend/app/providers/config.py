from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import AppSettings
from app.models.projects import LlmProfile


DEEPSEEK_PROVIDER = "openai_compatible"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_KEY_REF = "env:DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class ResolvedLlmConfig:
    enabled: bool
    provider: str
    model: str
    base_url: str
    api_key_ref: str

    @property
    def complete(self) -> bool:
        return self.enabled and bool(os.environ.get("DEEPSEEK_API_KEY"))


def resolve_llm_config(settings: AppSettings, profile: LlmProfile | None = None) -> ResolvedLlmConfig:
    """Resolve the same DeepSeek environment contract as the Java platform.

    The Python platform intentionally does not auto-detect other vendor
    variables. The model, endpoint, and secret reference remain fixed to the
    original DeepSeek configuration; only the secret value is resolved by the
    HTTP provider at request time.
    """

    project = profile or LlmProfile()
    return ResolvedLlmConfig(
        enabled=bool(project.enabled or settings.llm_enabled or os.environ.get("DEEPSEEK_API_KEY")),
        provider=DEEPSEEK_PROVIDER,
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        api_key_ref=DEEPSEEK_KEY_REF,
    )
