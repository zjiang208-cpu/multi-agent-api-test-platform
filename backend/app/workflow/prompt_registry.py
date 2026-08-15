from __future__ import annotations

import hashlib
import sys
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field

from app.models.projects import StrictModel


class PromptRetryPolicy(StrictModel):
    max_attempts: int = Field(default=1, ge=1, le=3)


class PromptDefinition(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    output_model: str = Field(min_length=1, max_length=120)
    system_prompt: str = Field(min_length=1)
    few_shot_examples: list[str] = Field(default_factory=list, max_length=10)
    rules: list[str] = Field(default_factory=list, max_length=200)
    quality_checks: list[str] = Field(default_factory=list, max_length=100)
    retry: PromptRetryPolicy = Field(default_factory=PromptRetryPolicy)

    def render_system_prompt(self) -> str:
        sections = [self.system_prompt.strip()]
        if self.few_shot_examples:
            sections.append(
                "Few-Shot 示例（仅示范结构和决策边界，示例中的 ID、路径、字段和值都不是业务证据，禁止复制到真实输出）：\n"
                + "\n\n".join(
                    f"示例 {index}：\n{example.strip()}"
                    for index, example in enumerate(self.few_shot_examples, 1)
                )
            )
        if self.rules:
            sections.append(
                "硬性规则：\n"
                + "\n".join(f"{index}. {rule}" for index, rule in enumerate(self.rules, 1))
            )
        if self.quality_checks:
            sections.append(
                "输出前自检：\n" + "\n".join(f"- {item}" for item in self.quality_checks)
            )
        return "\n\n".join(sections)


class LoadedPrompt(StrictModel):
    definition: PromptDefinition
    sha256: str
    source_path: str

    @property
    def system_prompt(self) -> str:
        return self.definition.render_system_prompt()


PROMPT_DIRECTORY = Path(__file__).resolve().parents[2] / "config" / "prompts"
PROMPT_FILES = {
    "nlu": "nlu.v1.yaml",
    "designer": "designer.v1.yaml",
    "reviewer": "reviewer.v1.yaml",
}


@lru_cache(maxsize=16)
def load_prompt(name: str, prompt_directory: str | None = None) -> LoadedPrompt:
    directory = Path(prompt_directory).resolve() if prompt_directory else PROMPT_DIRECTORY
    filename = PROMPT_FILES.get(name)
    if filename is None:
        raise ValueError(f"unknown prompt: {name}")
    path = (directory / filename).resolve()
    if prompt_directory is None and not path.exists():
        directory = (Path(sys.prefix) / "config" / "prompts").resolve()
        path = (directory / filename).resolve()
    if path.parent != directory.resolve():
        raise ValueError("prompt path escaped configured prompt directory")
    raw = path.read_bytes()
    value = yaml.safe_load(raw.decode("utf-8"))
    definition = PromptDefinition.model_validate(value)
    if definition.name != name:
        raise ValueError(f"prompt name mismatch: expected {name}, got {definition.name}")
    return LoadedPrompt(
        definition=definition,
        sha256=hashlib.sha256(raw).hexdigest(),
        source_path=str(path),
    )


def prompt_manifest() -> dict[str, str]:
    manifest: dict[str, str] = {}
    for name in PROMPT_FILES:
        prompt = load_prompt(name)
        manifest[f"{name}_prompt_version"] = prompt.definition.version
        manifest[f"{name}_prompt_sha256"] = prompt.sha256
    return manifest
