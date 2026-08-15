from __future__ import annotations

from app.workflow.prompt_registry import load_prompt, prompt_manifest


NLU_PROMPT = load_prompt("nlu")
DESIGNER_PROMPT = load_prompt("designer")
REVIEWER_PROMPT = load_prompt("reviewer")

REQUIREMENT_AGENT_SYSTEM = NLU_PROMPT.system_prompt
DESIGNER_AGENT_SYSTEM = DESIGNER_PROMPT.system_prompt
REVIEWER_AGENT_SYSTEM = REVIEWER_PROMPT.system_prompt

PROMPT_MANIFEST = prompt_manifest()
WORKFLOW_PROMPT_VERSION = "|".join(
    f"{name}:{PROMPT_MANIFEST[f'{name}_prompt_version']}"
    for name in ("nlu", "designer", "reviewer")
)
