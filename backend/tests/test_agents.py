from __future__ import annotations

import json

import pytest

from app.models.contracts import OperationContract
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection as PointCollection
from app.providers.llm import CallBudget, FakeLlmProvider, ProviderError
from app.workflow.agents import LlmTelemetry, provider_agent
from app.workflow.models import RequirementAgentOutput
from app.workflow.prompts import (
    DESIGNER_AGENT_SYSTEM,
    PROMPT_MANIFEST,
    REQUIREMENT_AGENT_SYSTEM,
    REVIEWER_AGENT_SYSTEM,
    WORKFLOW_PROMPT_VERSION,
)


def _requirement() -> RequirementAgentOutput:
    operation = OperationContract(
        operation_id="get-item",
        method="GET",
        path="/items/{id}",
        responses=[{"status_code": 200}],
    )
    return RequirementAgentOutput(
        requirement=RequirementDocument(requirement_id="REQ-GET-ITEM-001", api=operation),
        test_points=PointCollection(
            requirement_id="REQ-GET-ITEM-001",
            requirement_version=1,
        ),
    )


def test_provider_agent_sends_structured_bounded_and_redacted_json():
    provider = FakeLlmProvider(lambda _: _requirement())
    agent = provider_agent(
        provider,
        system_prompt=REQUIREMENT_AGENT_SYSTEM,
        response_model=RequirementAgentOutput,
    )
    result = agent.invoke(
        {
            "operation": _requirement().requirement.api,
            "source_document": "password=raw-password api_key=raw-api-key",
            "evidence": EvidenceBundle(operation_id="get-item"),
        }
    )

    payload = json.loads(provider.calls[0]["user"])
    assert result.requirement.requirement_id == "REQ-GET-ITEM-001"
    assert payload["operation"]["operation_id"] == "get-item"
    assert "raw-password" not in provider.calls[0]["user"]
    assert "raw-api-key" not in provider.calls[0]["user"]
    assert "object at" not in provider.calls[0]["user"]


def test_provider_agent_does_not_silently_truncate_supported_requirement_documents():
    provider = FakeLlmProvider(lambda _: _requirement())
    agent = provider_agent(
        provider,
        system_prompt=REQUIREMENT_AGENT_SYSTEM,
        response_model=RequirementAgentOutput,
    )
    source_document = "A" * 30_000
    agent.invoke(
        {
            "operation": _requirement().requirement.api,
            "source_document": source_document,
            "evidence": EvidenceBundle(operation_id="get-item"),
        }
    )

    payload = json.loads(provider.calls[0]["user"])
    assert payload["source_document"] == source_document


def test_provider_agent_shares_a_call_budget_across_workflow_nodes():
    provider = FakeLlmProvider(lambda _: _requirement())
    agent = provider_agent(
        provider,
        system_prompt=REQUIREMENT_AGENT_SYSTEM,
        response_model=RequirementAgentOutput,
        budget=CallBudget(max_calls=1),
    )
    payload = {"operation": _requirement().requirement.api, "evidence": EvidenceBundle(operation_id="get-item")}
    agent.invoke(payload)
    with pytest.raises(ProviderError, match="budget"):
        agent.invoke(payload)


def test_provider_agent_records_bounded_call_metrics():
    telemetry = LlmTelemetry()
    provider = FakeLlmProvider(lambda _: _requirement())
    agent = provider_agent(
        provider,
        system_prompt=REQUIREMENT_AGENT_SYSTEM,
        response_model=RequirementAgentOutput,
        telemetry=telemetry,
        stage="nlu",
    )

    agent.invoke(
        {
            "operation": _requirement().requirement.api,
            "evidence": EvidenceBundle(operation_id="get-item"),
        }
    )

    assert len(agent.last_metrics) == 1
    assert agent.last_metrics[0].status == "success"
    assert agent.last_metrics[0].input_chars > 0
    assert agent.last_metrics[0].output_chars > 0
    assert telemetry.metadata()["llm_nlu_calls"] == "1"


def test_case_prompts_publish_executor_constraints():
    assert WORKFLOW_PROMPT_VERSION == "nlu:1.2.7|designer:1.2.5|reviewer:1.2.5"
    assert len(PROMPT_MANIFEST["designer_prompt_sha256"]) == 64
    assert "status_code" in DESIGNER_AGENT_SYSTEM
    assert "mode=supplement" in DESIGNER_AGENT_SYSTEM
    assert "严格字段集合" in DESIGNER_AGENT_SYSTEM
    assert "suggested_case_specs" in REVIEWER_AGENT_SYSTEM
    assert "N-1" in REQUIREMENT_AGENT_SYSTEM
    assert "不是游戏 UI 黑盒测试" in REQUIREMENT_AGENT_SYSTEM
