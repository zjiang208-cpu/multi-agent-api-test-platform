from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Process-level settings only; project settings live in TestProject."""

    model_config = SettingsConfigDict(
        env_prefix="AI_TEST_",
        env_file=None,
        extra="ignore",
    )

    app_name: str = "基于 Multi-Agent 的接口自动化测试平台"
    environment: str = "local"
    api_prefix: str = "/api"
    data_dir: Path = Path(".data")
    allow_remote_targets: bool = False
    allow_remote_sources: bool = False
    llm_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_model: str | None = None
    llm_api_key_ref: str | None = None
    llm_base_url: str | None = None
    max_projects: int = Field(default=100, ge=1, le=10_000)
    max_response_body_length: int = Field(default=12_000, ge=100, le=10_000_000)

    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()
