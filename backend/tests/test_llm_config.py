from __future__ import annotations

from app.core.config import AppSettings
from app.models.projects import LlmProfile
from app.providers.config import resolve_llm_config


def test_original_deepseek_environment_contract_is_used(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "do-not-return")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_MODEL", "must-not-be-used")

    resolved = resolve_llm_config(AppSettings(), LlmProfile())

    assert resolved.enabled is True
    assert resolved.complete is True
    assert resolved.provider == "openai_compatible"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.base_url == "https://api.deepseek.com/v1"
    assert resolved.api_key_ref == "env:DEEPSEEK_API_KEY"
    assert "do-not-return" not in repr(resolved)


def test_other_vendor_environment_does_not_change_deepseek_selection(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_MODEL", "must-not-be-used")

    resolved = resolve_llm_config(AppSettings(), LlmProfile())

    assert resolved.provider == "openai_compatible"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.base_url == "https://api.deepseek.com/v1"
    assert resolved.api_key_ref == "env:DEEPSEEK_API_KEY"
    assert resolved.complete is False
