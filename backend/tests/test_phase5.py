from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from app.models.cases import CaseSet, TestCase as CaseModel
from app.models.evidence import EvidenceBundle, EvidenceFact
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPoint as PointModel, TestPointCollection as PointCollection
from app.providers.llm import CallBudget, FakeLlmProvider, ProviderError, StructuredOutputParser
from app.providers.llm import OpenAICompatibleProvider, SecretReferenceError
from app.designer.service import DesignerService
from app.reviewer.service import OnePassReviewService
from app.workflow.models import ReviewerAgentOutput


class JsonValue(BaseModel):
    value: int


def case_fixture(requirement_id: str, point_id: str, evidence_id: str, *, case_id: str = "CASE-1") -> CaseModel:
    return CaseModel(
        case_id=case_id,
        requirement_id=requirement_id,
        test_point_ids=[point_id],
        title="Valid item lookup",
        category="positive",
        priority="high",
        steps=["Send a valid request"],
        expected_behavior="The item is returned.",
        request={"method": "GET", "path": "/items/{id}", "path_params": {"id": 1}},
        assertions=[
            {
                "assertion_id": "A-1",
                "type": "status_code",
                "expected": 200,
                "evidence_refs": [evidence_id],
            }
        ],
        evidence_refs=[evidence_id],
    )


def test_structured_parser_budget_and_designer_validation():
    parsed = StructuredOutputParser.parse("```json\n{\"value\": 3}\n```", JsonValue)
    assert parsed.value == 3
    wrapped = StructuredOutputParser.parse("Here is the JSON:\n{\"value\": 4}\nDone.", JsonValue)
    assert wrapped.value == 4
    budget = CallBudget(max_calls=1)
    budget.consume()
    with pytest.raises(ProviderError):
        budget.consume()

    requirement = RequirementDocument(
        requirement_id="REQ-1",
        api={"operation_id": "get-item", "method": "GET", "path": "/items/{id}", "responses": [{"status_code": 200}]},
    )
    point = PointModel(
        point_id="TP-1",
        requirement_id="REQ-1",
        title="lookup",
        category="positive",
        action="lookup",
        expected_result="item returned",
        evidence_refs=["E-1"],
    )
    points = PointCollection(requirement_id="REQ-1", requirement_version=1, points=[point])
    evidence = EvidenceBundle(
        operation_id="get-item",
        facts=[EvidenceFact(evidence_id="E-1", source_type="openapi", reference="op:get-item", fact="contract")],
    )
    provider = FakeLlmProvider(
        lambda _: CaseSet(
            requirement_id="REQ-1",
            test_point_ids=["TP-1"],
            cases=[case_fixture("REQ-1", "TP-1", "E-1")],
        )
    )
    result = DesignerService(provider).design(requirement, points, evidence)
    assert result.cases[0].source == "initial"
    assert provider.calls


def test_structured_parser_exposes_bounded_schema_repair_context():
    with pytest.raises(ProviderError) as captured:
        StructuredOutputParser.parse(
            '{"value":"wrong","token":"must-not-persist"}',
            JsonValue,
        )

    error = captured.value
    assert error.category == "schema_validation"
    assert error.validation_issues == ("$.value: int_parsing",)
    assert error.repair_payload == {"value": "wrong", "token": "<redacted>"}
    assert "must-not-persist" not in str(error)


def test_one_pass_reviewer_reports_omissions_without_scoring_or_repair():
    requirement = RequirementDocument(
        requirement_id="REQ-1",
        api={"operation_id": "get-item", "method": "GET", "path": "/items/{id}", "responses": [{"status_code": 200}]},
    )
    points = PointCollection(
        requirement_id="REQ-1",
        requirement_version=1,
        points=[
            PointModel(point_id="TP-1", requirement_id="REQ-1", title="one", category="positive", action="a", expected_result="e", evidence_refs=["E-1"]),
            PointModel(point_id="TP-2", requirement_id="REQ-1", title="two", category="positive", action="a", expected_result="e", evidence_refs=["E-1"]),
        ],
    )
    evidence = EvidenceBundle(
        operation_id="get-item",
        facts=[EvidenceFact(evidence_id="E-1", source_type="openapi", reference="op:get-item", fact="contract")],
    )
    initial_cases = CaseSet(requirement_id="REQ-1", cases=[case_fixture("REQ-1", "TP-1", "E-1")])
    review = OnePassReviewService().review(requirement, points, initial_cases, evidence)
    assert isinstance(review, ReviewerAgentOutput)
    assert review.missing_test_point_ids == ["TP-2"]
    assert "score" not in review.model_dump()


def test_openai_provider_requires_non_secret_environment_reference(monkeypatch):
    monkeypatch.delenv("PHASE5_LLM_KEY", raising=False)
    provider = OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        model="demo",
        api_key_ref="env:PHASE5_LLM_KEY",
    )
    with pytest.raises(SecretReferenceError):
        provider.complete(system="system", user="user", response_model=JsonValue)


def test_openai_provider_keeps_main_thinking_and_captures_safe_call_metadata(monkeypatch):
    monkeypatch.setenv("PHASE5_LLM_KEY", "do-not-return")
    captured_payload = {}

    def fake_post(url, *, headers, json, timeout, follow_redirects):
        captured_payload.update(json)
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"value":7}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 45,
                    "completion_tokens_details": {"reasoning_tokens": 30},
                },
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        model="demo",
        api_key_ref="env:PHASE5_LLM_KEY",
    )

    result = provider.complete(
        system="Return JSON",
        user="input",
        response_model=JsonValue,
        thinking_mode="enabled",
    )

    assert result.value == 7
    assert captured_payload["thinking"] == {"type": "enabled"}
    assert captured_payload["response_format"] == {"type": "json_object"}
    assert captured_payload["max_tokens"] == 32_768
    assert provider.last_call_info.finish_reason == "stop"
    assert provider.last_call_info.prompt_tokens == 120
    assert provider.last_call_info.completion_tokens == 45
    assert provider.last_call_info.reasoning_tokens == 30
