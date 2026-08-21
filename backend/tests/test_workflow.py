from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evidence.providers.database import DatabaseFixtureResolver
from app.models.auth import AuthProtocol
from app.models.cases import Assertion, CaseSet, TestCase
from app.models.contracts import OperationContract, SourceReference
from app.models.evidence import EvidenceBundle, EvidenceFact
from app.models.projects import ProjectSettings, TestProject, TestProjectCreate
from app.models.requirements import RequirementDocument, RequirementEvidenceRef
from app.models.testpoints import TestPoint, TestPointCollection
from app.projects.service import ProjectService
from app.projects.store import ProjectStore
from app.requirements.operation_store import OperationStore
from app.workflow.agents import fake_agent
from app.workflow.graph import ApiTestWorkflow
from app.workflow.models import (
    DesignerAgentOutput,
    RequirementAgentOutput,
    RequirementApproval,
    ReviewerAgentOutput,
    SuggestedCaseSpec,
)


def _project_and_operation(tmp_path: Path) -> tuple[ProjectService, str, OperationContract]:
    project = TestProject.new(
        TestProjectCreate(
            name="Workflow test project",
            settings=ProjectSettings(sut_target={"base_url": "http://127.0.0.1:8081"}),
        )
    )
    project_store = ProjectStore(tmp_path)
    project_store.save(project)
    operation = OperationContract(
        operation_id="get-item",
        method="GET",
        path="/items/{id}",
        summary="Get an item",
        parameters=[{"name": "id", "location": "path", "required": True, "type": "integer"}],
        responses=[{"status_code": 200}, {"status_code": 404}],
    )
    OperationStore(tmp_path, project.project_id).save_many([operation])
    return ProjectService(project_store), project.project_id, operation


def test_requirement_excerpt_uses_current_operation_source_range_not_path_prefix():
    document = """# Get item
GET /items/{id}
response: item detail fields

# Create item
POST /items
response: created item id only
"""
    operation = OperationContract(
        operation_id="post-item",
        method="POST",
        path="/items",
        source_document_id="doc-1",
        source_refs=[
            SourceReference(
                source_document_id="doc-1",
                start_line=6,
                end_line=7,
                reference="document:doc-1:lines:6-7",
            )
        ],
        responses=[{"status_code": 200}],
    )

    excerpt = ApiTestWorkflow._operation_requirement_excerpt(operation, document)

    assert "created item id only" in excerpt
    assert "item detail fields" not in excerpt

    # The fallback matcher must also reject a same-method sibling whose path
    # merely starts with the current path.
    excerpt_without_source_range = ApiTestWorkflow._operation_requirement_excerpt(
        operation.model_copy(update={"source_refs": []}),
        document,
    )
    assert "created item id only" in excerpt_without_source_range
    assert "item detail fields" not in excerpt_without_source_range


def test_requirement_excerpt_keeps_response_rules_under_same_api_heading():
    document = """# Get item
## 1. Basic information
GET /items/{id}
## 2. Path parameter
id must be greater than 0
## 3. Failure scenarios
HTTP 200, success=false, errorMsg is `item id is invalid`

# Create item
POST /items
"""
    operation = OperationContract(
        operation_id="get-item",
        method="GET",
        path="/items/{id}",
        source_document_id="doc-1",
        source_refs=[
            SourceReference(
                source_document_id="doc-1",
                start_line=3,
                end_line=3,
                reference="document:doc-1:lines:3-3",
            )
        ],
        responses=[{"status_code": 200}],
    )

    excerpt = ApiTestWorkflow._operation_requirement_excerpt(operation, document)

    assert "success=false" in excerpt
    assert "item id is invalid" in excerpt
    assert "POST /items" not in excerpt


def test_nlu_receives_current_operation_excerpt_instead_of_full_document(tmp_path):
    project_service, project_id, operation = _project_and_operation(tmp_path)
    captured: dict[str, str | None] = {}

    def requirement_factory(payload):
        captured["source_document"] = payload["source_document"]
        requirement = RequirementDocument(
            requirement_id="REQ-CURRENT-OPERATION",
            api=payload["operation"],
        )
        return RequirementAgentOutput(
            requirement=requirement,
            test_points=TestPointCollection(
                requirement_id=requirement.requirement_id,
                requirement_version=1,
                points=[],
            ),
        )

    workflow = ApiTestWorkflow(
        project_service=project_service,
        data_dir=tmp_path,
        nlu_agent=fake_agent(RequirementAgentOutput, requirement_factory),
        designer_agent=fake_agent(DesignerAgentOutput, lambda _: None),
        reviewer_agent=fake_agent(ReviewerAgentOutput, lambda _: None),
    )
    workflow.invoke_nlu(
        {
            "workflow_id": "workflow-current-operation-context",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "input_document": (
                "# 查询条目\n"
                "GET /items/{id}\n"
                "id | Integer | 是 | 条目 ID\n"
                "\n"
                "# 创建条目\n"
                "POST /items\n"
                "name | String | 是 | 条目名称\n"
            ),
            "events": [],
            "errors": [],
        }
    )

    assert captured["source_document"] is not None
    assert "id | Integer | 是 | 条目 ID" in captured["source_document"]
    assert "创建条目" not in captured["source_document"]
    assert "name | String" not in captured["source_document"]


def test_auth_context_keeps_document_level_protocol_without_neighboring_operation_rules():
    document = """# API rules

## 当前协议约定

- Token 直接放入 authorization，不使用 Bearer 前缀。

## 1. 查询当前用户

GET /user/me
响应字段：id、nickName、icon

## 2. 查询商户

GET /shop/{id}
响应字段：name、address
"""
    operation = OperationContract(
        operation_id="get-user-me",
        method="GET",
        path="/user/me",
        source_document_id="doc-1",
        source_refs=[
            SourceReference(
                source_document_id="doc-1",
                start_line=9,
                end_line=11,
                reference="document:doc-1:lines:9-11",
            )
        ],
        responses=[{"status_code": 200}],
    )

    excerpt = ApiTestWorkflow._operation_requirement_excerpt(operation, document)
    context = ApiTestWorkflow._operation_auth_context(operation, document, excerpt)

    assert "不使用 Bearer 前缀" in context
    assert "id、nickName、icon" in context
    assert "name、address" not in context


def test_nlu_retains_expired_token_negative_and_marks_missing_fixture(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    requirement = RequirementDocument(
        requirement_id="REQ-GET-ITEM-001",
        api=operation,
        unresolved_questions=[],
    )
    points = TestPointCollection(
        requirement_id=requirement.requirement_id,
        requirement_version=1,
        points=[
            TestPoint(
                point_id="TP-MISSING-AUTH",
                requirement_id=requirement.requirement_id,
                title="缺少 Authorization 返回 401",
                category="negative",
                action="不携带 Authorization 请求头。",
                expected_result="返回 401。",
            ),
            TestPoint(
                point_id="TP-EXPIRED-AUTH",
                requirement_id=requirement.requirement_id,
                title="过期 Token 返回 401",
                category="negative",
                action="使用过期 Token 请求接口。",
                expected_result="返回 401。",
            ),
        ],
    )

    normalized_requirement, normalized_points = workflow._normalize_auth_protocol_output(
        requirement,
        points,
        AuthProtocol(status="explicit", prefix=None),
        EvidenceBundle(operation_id=operation.operation_id, facts=[]),
    )

    assert [point.point_id for point in normalized_points.points] == [
        "TP-MISSING-AUTH",
        "TP-EXPIRED-AUTH",
    ]
    assert any("过期 Token 负例" in item for item in normalized_requirement.unresolved_questions)


def test_nlu_binds_available_nonexistent_auth_fixture(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    requirement = RequirementDocument(
        requirement_id="REQ-GET-ITEM-001",
        api=operation,
    )
    points = TestPointCollection(
        requirement_id=requirement.requirement_id,
        requirement_version=1,
        points=[
            TestPoint(
                point_id="TP-NONEXISTENT-AUTH",
                requirement_id=requirement.requirement_id,
                title="不存在 Token 返回 401",
                category="negative",
                action="使用不存在 Token 请求接口。",
                expected_result="返回 401。",
            )
        ],
    )
    fixture = EvidenceFact(
        evidence_id="E-AUTH-NONEXISTENT",
        source_type="auth_fixture",
        reference="auth-fixture:get-item:nonexistent-token",
        fact="$AUTH_FIXTURE[nonexistent:token] is available.",
        metadata={
            "fixture_kind": "nonexistent",
            "token_placeholder": "$AUTH_FIXTURE[nonexistent:token]",
        },
    )

    normalized_requirement, normalized_points = workflow._normalize_auth_protocol_output(
        requirement,
        points,
        AuthProtocol(status="explicit", prefix=None),
        EvidenceBundle(operation_id=operation.operation_id, facts=[fixture]),
    )

    assert "$AUTH_FIXTURE[nonexistent:token]" in normalized_points.points[0].action
    assert "E-AUTH-NONEXISTENT" in normalized_points.points[0].evidence_refs
    assert any(ref.evidence_id == "E-AUTH-NONEXISTENT" for ref in normalized_requirement.evidence_refs)


def test_nlu_merges_expired_and_nonexistent_auth_failures_with_same_401(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    requirement = RequirementDocument(
        requirement_id="REQ-GET-ITEM-001",
        api=operation,
    )
    points = TestPointCollection(
        requirement_id=requirement.requirement_id,
        requirement_version=1,
        points=[
            TestPoint(
                point_id="TP-EXPIRED-AUTH",
                requirement_id=requirement.requirement_id,
                title="过期 Token 返回 401",
                category="negative",
                action="使用过期 Token 请求接口。",
                expected_result="返回 HTTP 401。",
            ),
            TestPoint(
                point_id="TP-NONEXISTENT-AUTH",
                requirement_id=requirement.requirement_id,
                title="不存在 Token 返回 401",
                category="negative",
                action="使用不存在 Token 请求接口。",
                expected_result="返回 HTTP 401。",
            ),
        ],
    )
    fixture = EvidenceFact(
        evidence_id="E-AUTH-NONEXISTENT",
        source_type="auth_fixture",
        reference="auth-fixture:get-item:nonexistent-token",
        fact="$AUTH_FIXTURE[nonexistent:token] is available.",
        metadata={
            "fixture_kind": "nonexistent",
            "token_placeholder": "$AUTH_FIXTURE[nonexistent:token]",
        },
    )

    normalized_requirement, normalized_points = workflow._normalize_auth_protocol_output(
        requirement,
        points,
        AuthProtocol(status="explicit", prefix=None),
        EvidenceBundle(operation_id=operation.operation_id, facts=[fixture]),
    )

    assert len(normalized_points.points) == 1
    assert normalized_points.points[0].title == "过期/不存在 Token 返回 401"
    assert "$AUTH_FIXTURE[nonexistent:token]" in normalized_points.points[0].action
    assert not normalized_requirement.unresolved_questions


def test_nlu_canonicalizes_single_nonexistent_auth_point_to_combined_semantics(tmp_path):
    workflow, _, operation, _ = _build_workflow(tmp_path)
    requirement = RequirementDocument(
        requirement_id="REQ-GET-ITEM-001",
        api=operation,
        business_rules=["缺少、过期或不存在的 Token 返回 HTTP 401。"],
        expected_behaviors=[
            "携带不存在的 Token 返回 HTTP 401。",
            "携带过期 Token 返回 HTTP 401。",
        ],
    )
    points = TestPointCollection(
        requirement_id=requirement.requirement_id,
        requirement_version=1,
        points=[
            TestPoint(
                point_id="TP-NONEXISTENT-AUTH",
                requirement_id=requirement.requirement_id,
                title="不存在 Token 返回 401",
                category="negative",
                action="使用不存在 Token 请求接口。",
                expected_result="返回 HTTP 401。",
            )
        ],
    )
    fixture = EvidenceFact(
        evidence_id="E-AUTH-NONEXISTENT",
        source_type="auth_fixture",
        reference="auth-fixture:get-item:nonexistent-token",
        fact="Use $AUTH_FIXTURE[nonexistent:token].",
        metadata={
            "fixture_kind": "nonexistent",
            "token_placeholder": "$AUTH_FIXTURE[nonexistent:token]",
        },
    )

    normalized_requirement, normalized_points = workflow._normalize_auth_protocol_output(
        requirement,
        points,
        AuthProtocol(status="explicit", prefix=None),
        EvidenceBundle(operation_id=operation.operation_id, facts=[fixture]),
    )

    assert len(normalized_points.points) == 1
    assert normalized_points.points[0].title == "过期/不存在 Token 返回 401"
    assert normalized_requirement.expected_behaviors == [
        "携带过期/不存在 Token 时返回 HTTP 401，通常无响应体。"
    ]


def test_designer_redacted_negative_auth_header_is_canonicalized_to_fixture():
    fixture = EvidenceFact(
        evidence_id="E-AUTH-NONEXISTENT",
        source_type="auth_fixture",
        reference="auth-fixture:get-item:nonexistent-token",
        fact="$AUTH_FIXTURE[nonexistent:token] is available.",
        metadata={
            "fixture_kind": "nonexistent",
            "token_placeholder": "$AUTH_FIXTURE[nonexistent:token]",
        },
    )
    case = TestCase(
        case_id="CASE-AUTH-NEGATIVE",
        requirement_id="REQ-GET-ITEM-001",
        test_point_ids=["TP-AUTH-NEGATIVE"],
        title="invalid token returns 401",
        category="negative",
        steps=["send request"],
        expected_behavior="HTTP 401",
        request={
            "method": "GET",
            "path": "/items/{id}",
            "path_params": {"id": 1},
            "headers": {"Authorization": "<redacted>"},
        },
        assertions=[
            {
                "assertion_id": "ASSERT-401",
                "type": "status_code",
                "expected": 401,
                "evidence_refs": ["E-REQ"],
            }
        ],
        evidence_refs=["E-REQ"],
    )
    missing_header = case.model_copy(
        update={
            "case_id": "CASE-AUTH-MISSING",
            "request": case.request.model_copy(update={"headers": {}}),
        }
    )
    normalized = ApiTestWorkflow._canonicalize_redacted_auth_cases(
        CaseSet(requirement_id="REQ-GET-ITEM-001", cases=[case, missing_header]),
        {
            "evidence": EvidenceBundle(operation_id="get-item", facts=[fixture]),
            "auth_protocol": AuthProtocol(status="explicit", prefix=None),
        },
    )

    assert normalized.cases[0].request.headers["Authorization"] == "$AUTH_FIXTURE[nonexistent:token]"
    assert "E-AUTH-NONEXISTENT" in normalized.cases[0].evidence_refs
    assert normalized.cases[1].request.headers == {}


def _build_workflow(tmp_path: Path, *, with_gap: bool = False):
    project_service, project_id, operation = _project_and_operation(tmp_path)
    calls = {"requirement": 0, "designer": 0, "reviewer": 0}

    def requirement_factory(payload):
        calls["requirement"] += 1
        evidence = payload["evidence"]
        requirement = RequirementDocument(
            requirement_id="REQ-GET-ITEM-001",
            api=operation,
            preconditions=["The path id is available."],
            business_rules=["The API returns the documented item response."],
            expected_behaviors=["HTTP 200 or 404 is returned."],
            evidence_refs=[
                RequirementEvidenceRef(
                    evidence_id=evidence.facts[0].evidence_id,
                    source_type=evidence.facts[0].source_type,
                    reference=evidence.facts[0].reference,
                )
            ],
        )
        evidence_id = payload["evidence"].facts[0].evidence_id
        return RequirementAgentOutput(
            requirement=requirement,
            test_points=TestPointCollection(
                requirement_id=requirement.requirement_id,
                requirement_version=requirement.version,
                points=[
                    TestPoint(
                        point_id="TP-VALID",
                        requirement_id=requirement.requirement_id,
                        title="Valid item lookup",
                        category="positive",
                        priority="high",
                        action="Send a valid item id.",
                        expected_result="The item response is returned.",
                        evidence_refs=[evidence_id],
                    ),
                    TestPoint(
                        point_id="TP-MISSING",
                        requirement_id=requirement.requirement_id,
                        title="Missing item lookup",
                        category="negative",
                        action="Send an id that is not present.",
                        expected_result="The API returns the documented failure response.",
                        evidence_refs=[evidence_id],
                    ),
                ],
            )
        )

    def case_factory(payload, *, case_id: str, point_id: str, source: str) -> TestCase:
        requirement = payload["requirement"]
        evidence_id = payload["evidence"].facts[0].evidence_id
        return TestCase(
            case_id=case_id,
            requirement_id=requirement.requirement_id,
            test_point_ids=[point_id],
            title=f"Case for {point_id}",
            category="positive" if point_id == "TP-VALID" else "negative",
            priority="high",
            steps=["Render the request", "Send the request"],
            expected_behavior="The documented response is returned.",
            request={
                "method": "GET",
                "path": "/items/{id}",
                "path_params": {"id": 1 if point_id == "TP-VALID" else 999999},
            },
            assertions=[
                Assertion(
                    assertion_id=f"ASSERT-{case_id}",
                    type="status_code",
                    expected=200 if point_id == "TP-VALID" else 404,
                    evidence_refs=[evidence_id],
                )
            ],
            evidence_refs=[evidence_id],
            source=source,
        )

    def designer_factory(payload):
        calls["designer"] += 1
        supplement = payload.get("mode") == "supplement"
        case = case_factory(
            payload,
            case_id="CASE-REVIEWER-ADDED" if supplement else "CASE-INITIAL",
            point_id="TP-MISSING" if supplement else "TP-VALID",
            source="reviewer_added" if supplement else "initial",
        )
        return DesignerAgentOutput(
            draft_cases=CaseSet(
                requirement_id=payload["requirement"].requirement_id,
                test_point_ids=["TP-MISSING" if supplement else "TP-VALID"],
                cases=[case],
            )
        )

    def reviewer_factory(payload):
        calls["reviewer"] += 1
        if payload.get("review_stage") == "final":
            return ReviewerAgentOutput(
                remaining_gaps=["A gap remains for manual clarification."] if with_gap else []
            )
        return ReviewerAgentOutput(
            missing_test_point_ids=["TP-MISSING"],
            remaining_gaps=["A gap remains for manual clarification."] if with_gap else [],
            suggested_case_specs=[
                SuggestedCaseSpec(
                    spec_id="SPEC-MISSING",
                    target_test_point_ids=["TP-MISSING"],
                    title="Missing item lookup",
                    reason="The negative lookup Test Point is not semantically covered.",
                    category="negative",
                    priority="high",
                    required_assertions=["HTTP 404 status"],
                    evidence_refs=[payload["evidence"].facts[0].evidence_id],
                )
            ],
        )

    workflow = ApiTestWorkflow(
        project_service=project_service,
        data_dir=tmp_path,
        nlu_agent=fake_agent(RequirementAgentOutput, requirement_factory),
        designer_agent=fake_agent(DesignerAgentOutput, designer_factory),
        reviewer_agent=fake_agent(ReviewerAgentOutput, reviewer_factory),
    )
    return workflow, project_id, operation, calls


def _invoke_approved_workflow(workflow, state):
    nlu = workflow.invoke_nlu(state)
    requirement = nlu["requirement"]
    points = nlu["test_points"]
    approval = RequirementApproval(
        workflow_id=state["workflow_id"],
        project_id=state["project_id"],
        requirement_id=requirement.requirement_id,
        requirement_version=requirement.version,
        requirement_fingerprint="test-fingerprint",
        test_point_count=len(points.points),
        approved_at=datetime.now(timezone.utc),
    )
    return workflow.invoke_after_requirement_approval(
        {**nlu, "requirement_approval": approval}
    )


def test_compatibility_invoke_stops_at_requirement_approval(tmp_path):
    workflow, project_id, operation, calls = _build_workflow(tmp_path)
    result = workflow.invoke(
        {
            "workflow_id": "workflow-mandatory-gate",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        }
    )

    assert result["status"] == "WAITING_REQUIREMENT_APPROVAL"
    assert "draft_cases" not in result
    assert calls == {"requirement": 1, "designer": 0, "reviewer": 0}


def test_requirement_markdown_is_collected_as_first_class_evidence(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    markdown = (
        ("其他接口说明。\n" * 1_500)
        + "# 查询条目\n\n路径 `/items/{id}`，不存在的条目返回 item not found。"
    )
    result = workflow.invoke_nlu(
        {
            "workflow_id": "workflow-markdown-evidence",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "input_document_id": "reqdoc-markdown-test",
            "input_document": markdown,
            "events": [],
            "errors": [],
        }
    )

    document_facts = [
        fact for fact in result["evidence"].facts
        if fact.source_type == "requirement_document"
    ]
    assert len(document_facts) == 1
    assert document_facts[0].evidence_id.startswith("evidence-requirement-")
    assert document_facts[0].reference == "requirement_document:reqdoc-markdown-test"
    assert "item not found" in document_facts[0].fact
    assert result["evidence"].provider_status["requirement_document"] == "collected"


def test_langgraph_runs_one_bounded_supplement_pass_without_scoring(tmp_path):
    workflow, project_id, operation, calls = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-one-pass",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "include_optional_evidence": False,
            "events": [],
            "errors": [],
        }
    )

    assert result["status"] == "FINAL_CASES_READY"
    assert result["final_cases"].status == "READY"
    assert [case.case_id for case in result["final_cases"].cases] == [
        "CASE-INITIAL",
        "CASE-REVIEWER-ADDED",
    ]
    assert result["final_cases"].added_case_ids == ["CASE-REVIEWER-ADDED"]
    assert [event["node"] for event in result["events"]] == [
        "document_parser",
        "evidence_retriever",
        "nlu_agent",
        "designer_agent",
        "reviewer_agent",
        "supplement_designer_agent",
        "local_final_validator",
        "final_case_assembler",
    ]
    assert calls == {"requirement": 1, "designer": 2, "reviewer": 1}
    assert "score" not in result["reviewer_output"].model_dump()


def test_reviewer_gap_is_retained_after_single_bounded_supplement_pass(tmp_path):
    workflow, project_id, operation, calls = _build_workflow(tmp_path, with_gap=True)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-gap",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        }
    )

    assert result["status"] == "FINAL_CASES_READY"
    assert result["final_cases"].status == "READY"
    assert result["final_cases"].remaining_gaps == ["A gap remains for manual clarification."]
    assert calls["designer"] == 2
    assert calls["reviewer"] == 1


def test_incomplete_supplement_is_retained_without_second_reviewer(tmp_path, monkeypatch):
    workflow, project_id, operation, calls = _build_workflow(tmp_path)
    monkeypatch.setattr(
        workflow,
        "_supplement_spec_gaps",
        lambda _spec, _cases: ["required assertion remains unverified"],
    )

    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-local-final-gap",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )

    assert result["status"] == "FINAL_CASES_READY"
    assert "final_reviewer_agent" not in [event["node"] for event in result["events"]]
    assert result["reviewer_output"].suggested_case_specs == []
    assert any("required assertion remains unverified" in gap for gap in result["reviewer_output"].remaining_gaps)
    assert result["final_cases"].assembly_errors == []
    assert calls == {"requirement": 1, "designer": 2, "reviewer": 1}


def test_final_assembler_releases_executable_cases_with_partial_test_point_coverage(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-partial-coverage",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )
    extra_point = result["test_points"].points[0].model_copy(
        update={"point_id": "TP-UNRESOLVED-FIXTURE"}
    )
    assembled = workflow._final_case_assembler(
        {
            **result,
            "test_points": result["test_points"].model_copy(
                update={"points": [*result["test_points"].points, extra_point]}
            ),
        }
    )

    assert assembled["status"] == "FINAL_CASES_READY"
    assert assembled["final_cases"].status == "READY"
    assert assembled["final_cases"].assembly_errors == []
    assert any("TP-UNRESOLVED-FIXTURE" in gap for gap in assembled["final_cases"].remaining_gaps)


def test_downstream_agents_receive_only_nlu_referenced_evidence(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    nlu = workflow.invoke_nlu(
        {
            "workflow_id": "workflow-pruned-evidence",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        }
    )
    unrelated = EvidenceFact(
        evidence_id="evidence-unrelated-table",
        source_type="database_schema",
        reference="schema:unrelated_table",
        fact="An unrelated table schema.",
    )
    state = {
        **nlu,
        "evidence": nlu["evidence"].model_copy(
            update={"facts": [*nlu["evidence"].facts, unrelated]}
        ),
    }

    downstream = workflow._downstream_evidence(state)

    referenced = {
        reference.evidence_id for reference in nlu["requirement"].evidence_refs
    }
    referenced.update(
        evidence_id
        for point in nlu["test_points"].points
        for evidence_id in point.evidence_refs
    )
    assert {fact.evidence_id for fact in downstream.facts} == referenced
    assert unrelated.evidence_id not in {fact.evidence_id for fact in downstream.facts}


def test_explicit_exclusive_lower_bound_keeps_boundary_and_below_partition(tmp_path):
    _, _, operation = _project_and_operation(tmp_path)
    evidence_id = "evidence-requirement-boundary"
    requirement = RequirementDocument(
        requirement_id="REQ-BOUNDARY",
        api=operation,
        business_rules=["Path parameter id is a Long value greater than 0."],
        expected_behaviors=["When id is not greater than 0, errorMsg is 'item id is invalid'."],
        evidence_refs=[
            RequirementEvidenceRef(
                evidence_id=evidence_id,
                source_type="requirement_document",
                reference="requirement_document:reqdoc-boundary",
            )
        ],
    )
    original = TestPointCollection(
        requirement_id=requirement.requirement_id,
        requirement_version=1,
        points=[
            TestPoint(
                point_id="TP-ID-ZERO",
                requirement_id=requirement.requirement_id,
                title="id equals 0",
                category="boundary",
                action="Send id=0.",
                expected_result="The documented invalid result is returned.",
                evidence_refs=[evidence_id],
                parameter_refs=["id"],
            ),
            TestPoint(
                point_id="TP-ID-ONE-AMBIGUOUS",
                requirement_id=requirement.requirement_id,
                title="id equals 1",
                category="boundary",
                action="Send id=1.",
                expected_result=(
                    "If the row exists success is true; if it does not exist success is false."
                ),
                evidence_refs=[evidence_id],
                parameter_refs=["id"],
            ),
        ],
    )

    completed = ApiTestWorkflow._complete_explicit_numeric_boundary_points(
        original,
        requirement,
    )

    assert len(completed.points) == 3
    below = next(point for point in completed.points if point.point_id.startswith("TP-AUTO-"))
    assert "id=-1" in below.action
    assert below.category == "boundary"
    assert below.evidence_refs == [evidence_id]
    assert "TP-ID-ONE-AMBIGUOUS" in {point.point_id for point in completed.points}


def test_same_request_contract_case_is_folded_into_business_case():
    evidence_id = "evidence-contract"
    business = TestCase(
        case_id="CASE-ID-ZERO",
        requirement_id="REQ-CATEGORY",
        test_point_ids=["TP-ID-ZERO"],
        title="Invalid zero id",
        category="boundary",
        steps=["Send request"],
        expected_behavior="The request returns the documented invalid result.",
        request={"method": "GET", "path": "/items/{id}", "path_params": {"id": 0}},
        assertions=[Assertion(assertion_id="ASSERT-STATUS", type="status_code", expected=200)],
        evidence_refs=[evidence_id],
    )
    contract = TestCase(
        case_id="CASE-ID-ZERO-CONTRACT",
        requirement_id="REQ-CATEGORY",
        test_point_ids=["TP-RESPONSE-CONTRACT"],
        title="Generic response template",
        category="contract",
        steps=["Send the same request"],
        expected_behavior="The response uses the common envelope.",
        request={"method": "GET", "path": "/items/{id}", "path_params": {"id": "0"}},
        assertions=[
            Assertion(
                assertion_id="ASSERT-SCHEMA",
                type="response_schema",
                expected={
                    "type": "object",
                    "required": ["success"],
                    "properties": {"success": {"type": "boolean"}},
                },
            )
        ],
        evidence_refs=[evidence_id],
    )

    merged = ApiTestWorkflow._merge_cross_cutting_contract_cases([business, contract])

    assert len(merged) == 1
    assert merged[0].case_id == "CASE-ID-ZERO"
    assert merged[0].test_point_ids == ["TP-ID-ZERO", "TP-RESPONSE-CONTRACT"]
    assert {assertion.assertion_id for assertion in merged[0].assertions} == {
        "ASSERT-STATUS",
        "ASSERT-SCHEMA",
    }


def test_exact_valid_boundary_is_resolved_from_database_before_design(tmp_path, monkeypatch):
    database = tmp_path / "boundary.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table items (id integer primary key, name text not null);
        insert into items (id, name) values (1, 'boundary item');
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("BOUNDARY_TEST_DSN", f"sqlite:///{database.as_posix()}")

    project = TestProject.new(
        TestProjectCreate(
            name="Boundary fixture project",
            settings=ProjectSettings(
                sut_target={"base_url": "http://127.0.0.1:8081"},
                database={
                    "enabled": True,
                    "dialect": "sqlite",
                    "dsn_ref": "env:BOUNDARY_TEST_DSN",
                    "readonly": True,
                    "allowed_tables": ["items"],
                },
            ),
        )
    )
    store = ProjectStore(tmp_path / "projects")
    store.save(project)
    project_service = ProjectService(store)
    operation = OperationContract(
        operation_id="get-item-boundary",
        method="GET",
        path="/items/{id}",
        parameters=[{"name": "id", "location": "path", "required": True, "type": "integer"}],
        responses=[{"status_code": 200}],
    )
    fixture_fact = EvidenceFact(
        evidence_id="evidence-boundary-fixture",
        source_type="database_fixture",
        reference="database-fixture:items",
        operation_id=operation.operation_id,
        fact=(
            "Tokens: existing id=$DB_FIXTURE[existing:items:id]; "
            "absent id=$DB_FIXTURE[absent:items:id]."
        ),
        metadata={"table": "items", "read_only": "true"},
    )
    requirement = RequirementDocument(
        requirement_id="REQ-EXACT-BOUNDARY",
        api=operation,
        business_rules=["Path parameter id must be greater than 0."],
        expected_behaviors=[
            "If id=1 exists success is true; if id=1 is absent success is false."
        ],
        evidence_refs=[
            RequirementEvidenceRef(
                evidence_id=fixture_fact.evidence_id,
                source_type="database_fixture",
                reference=fixture_fact.reference,
            )
        ],
    )
    points = TestPointCollection(
        requirement_id=requirement.requirement_id,
        requirement_version=1,
        points=[
            TestPoint(
                point_id="TP-EXISTING",
                requirement_id=requirement.requirement_id,
                title="Existing item",
                category="positive",
                action="Use $DB_FIXTURE[existing:items:id] as id.",
                expected_result="HTTP 200 and success is true.",
                evidence_refs=[fixture_fact.evidence_id],
                parameter_refs=["id"],
            ),
            TestPoint(
                point_id="TP-ID-ONE",
                requirement_id=requirement.requirement_id,
                title="id=1 valid boundary",
                category="boundary",
                action="Send id=1.",
                expected_result=(
                    "If id=1 exists success is true; if id=1 is absent success is false."
                ),
                evidence_refs=[fixture_fact.evidence_id],
                parameter_refs=["id"],
            ),
        ],
    )
    workflow = object.__new__(ApiTestWorkflow)
    workflow.project_service = project_service
    state = {
        "project_id": project.project_id,
        "evidence": EvidenceBundle(
            operation_id=operation.operation_id,
            facts=[fixture_fact],
        ),
    }

    resolved_requirement, resolved_points = workflow._resolve_exact_numeric_boundary_fixtures(
        requirement,
        points,
        state,
    )

    boundary = next(point for point in resolved_points.points if point.point_id == "TP-ID-ONE")
    assert "$DB_FIXTURE[present:items:id:1]" in boundary.action
    assert boundary.expected_result == "HTTP 200 and success is true."
    assert all("if id=1" not in behavior.casefold() for behavior in resolved_requirement.expected_behaviors)

    boundary_case = TestCase(
        case_id="CASE-ID-ONE",
        requirement_id=requirement.requirement_id,
        test_point_ids=[boundary.point_id],
        title="Exact valid boundary",
        category="boundary",
        steps=["Send request"],
        expected_behavior=boundary.expected_result,
        request={"method": "GET", "path": "/items/{id}", "path_params": {"id": 1}},
        assertions=[Assertion(assertion_id="ASSERT-STATUS-ONE", type="status_code", expected=200)],
        evidence_refs=[fixture_fact.evidence_id],
    )
    normalized = workflow._normalize_case_list(
        [boundary_case],
        {"evidence": state["evidence"], "test_points": resolved_points},
    )[0]
    assert normalized.request.path_params["id"] == "$DB_FIXTURE[present:items:id:1]"
    executed = DatabaseFixtureResolver().resolve_case(normalized, project.settings)
    assert executed.request.path_params["id"] == 1


def test_local_reviewer_fast_path_checks_expected_business_value():
    case = TestCase(
        case_id="CASE-LOCAL-BUSINESS-VALUE",
        requirement_id="REQ-LOCAL",
        test_point_ids=["TP-LOCAL"],
        title="Business result",
        category="negative",
        steps=["Send request"],
        expected_behavior="The business request fails.",
        request={"method": "GET", "path": "/items/{id}", "path_params": {"id": -1}},
        assertions=[
            Assertion(
                assertion_id="ASSERT-LOCAL-SUCCESS",
                type="json_value",
                path="$.success",
                expected=False,
                operator="eq",
            ),
            Assertion(
                assertion_id="ASSERT-LOCAL-ERROR",
                type="json_value",
                path="$.errorMsg",
                expected="item not found",
                operator="eq",
            ),
        ],
    )

    assert ApiTestWorkflow._required_assertion_is_observed("$.success equals false", [case])
    assert ApiTestWorkflow._required_assertion_is_observed(
        "$.errorMsg equals `item not found`", [case]
    )
    assert not ApiTestWorkflow._required_assertion_is_observed("$.success equals true", [case])
    assert not ApiTestWorkflow._required_assertion_is_observed(
        "$.errorMsg equals `different message`", [case]
    )


def test_final_assembler_deduplicates_and_retains_bounded_repair_findings_as_gaps(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-dedupe-warning",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )
    duplicate = result["draft_cases"].cases[0].model_copy(
        update={"case_id": "CASE-DUPLICATE", "source": "reviewer_added"}
    )
    review = ReviewerAgentOutput(
        duplicate_case_ids=["CASE-INITIAL", "CASE-DUPLICATE"],
        suggested_case_specs=[
            SuggestedCaseSpec(
                spec_id="SPEC-MANUAL-FOLLOW-UP",
                target_test_point_ids=["TP-MISSING"],
                title="Manual follow-up",
                reason="The executor cannot observe the external cache state.",
                category="contract",
                required_assertions=["External cache state"],
                evidence_refs=[result["evidence"].facts[0].evidence_id],
            )
        ],
    )

    assembled = workflow._final_case_assembler(
        {
            **result,
            "supplemental_cases": [*result["supplemental_cases"], duplicate],
            "reviewer_output": review,
        }
    )

    assert assembled["status"] == "FINAL_CASES_READY"
    assert assembled["final_cases"].status == "READY"
    assert "CASE-DUPLICATE" not in {
        case.case_id for case in assembled["final_cases"].cases
    }
    assert assembled["final_cases"].assembly_errors == []
    assert any("Removed semantic duplicate case" in gap for gap in assembled["final_cases"].remaining_gaps)
    assert any("bounded repair limit" in gap.lower() for gap in assembled["final_cases"].remaining_gaps)


def test_final_assembler_merges_same_execution_across_different_test_points(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-merge-execution-duplicate",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )
    duplicate = result["draft_cases"].cases[0].model_copy(
        update={
            "case_id": "CASE-SAME-EXECUTION-DIFFERENT-POINT",
            "test_point_ids": ["TP-MISSING"],
            "preconditions": ["No authorization header is required."],
        }
    )

    assembled = workflow._final_case_assembler(
        {
            **result,
            "draft_cases": result["draft_cases"].model_copy(
                update={"cases": [result["draft_cases"].cases[0], duplicate]}
            ),
            "supplemental_cases": [],
            "reviewer_output": ReviewerAgentOutput(
                duplicate_case_ids=[duplicate.case_id]
            ),
        }
    )

    final_cases = assembled["final_cases"].cases
    assert [case.case_id for case in final_cases] == ["CASE-INITIAL"]
    assert final_cases[0].test_point_ids == ["TP-VALID", "TP-MISSING"]
    assert "No authorization header is required." in final_cases[0].preconditions
    assert any("Merged duplicate execution case" in gap for gap in assembled["final_cases"].remaining_gaps)


def test_final_assembler_removes_invalid_case_when_other_case_preserves_coverage(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-remove-invalid",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )
    valid_case = result["supplemental_cases"][0]
    redundant_invalid = valid_case.model_copy(
        update={
            "case_id": "CASE-INVALID-REDUNDANT",
            "source": "initial",
            "request": valid_case.request.model_copy(update={"path": "/wrong-path"}),
        }
    )
    assembled = workflow._final_case_assembler(
        {
            **result,
            "draft_cases": result["draft_cases"].model_copy(
                update={"cases": [*result["draft_cases"].cases, redundant_invalid]}
            ),
            "reviewer_output": ReviewerAgentOutput(
                invalid_case_ids=["CASE-INVALID-REDUNDANT"]
            ),
        }
    )

    assert assembled["status"] == "FINAL_CASES_READY"
    assert assembled["final_cases"].assembly_errors == []
    assert "CASE-INVALID-REDUNDANT" not in {
        case.case_id for case in assembled["final_cases"].cases
    }
    assert any(
        "Reviewer-invalid cases were removed" in gap
        for gap in assembled["final_cases"].remaining_gaps
    )


def test_final_assembler_keeps_case_when_only_one_assertion_is_unsupported(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-partial-assertion-warning",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )
    case = result["draft_cases"].cases[0].model_copy(
        update={
            "assertions": [
                *result["draft_cases"].cases[0].assertions,
                Assertion(
                    assertion_id="ASSERT-SECONDARY",
                    type="json_exists",
                    path="$.data",
                    expected=True,
                    evidence_refs=list(result["draft_cases"].cases[0].evidence_refs),
                ),
            ]
        }
    )
    unsupported_id = case.assertions[0].assertion_id
    assembled = workflow._final_case_assembler(
        {
            **result,
            "draft_cases": result["draft_cases"].model_copy(
                update={
                    "cases": [
                        case,
                        *[
                            item
                            for item in result["draft_cases"].cases
                            if item.case_id != case.case_id
                        ],
                    ]
                }
            ),
            "reviewer_output": ReviewerAgentOutput(
                invalid_case_ids=[case.case_id],
                unsupported_assertion_ids=[unsupported_id],
            ),
        }
    )

    assert assembled["status"] == "FINAL_CASES_READY"
    retained = next(
        item for item in assembled["final_cases"].cases if item.case_id == case.case_id
    )
    assert unsupported_id not in {item.assertion_id for item in retained.assertions}
    assert retained.assertions
    assert any(
        "removed or isolated at assertion level" in gap
        for gap in assembled["final_cases"].remaining_gaps
    )


def test_requirement_questions_are_retained_without_gating_complete_final_cases(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-question-warning",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        }
    )
    requirement = result["requirement"].model_copy(
        update={"unresolved_questions": ["Confirm the fuzzy matching rule."]}
    )
    assembled = workflow._final_case_assembler({**result, "requirement": requirement})

    assert assembled["status"] == "FINAL_CASES_READY"
    assert assembled["final_cases"].status == "READY"
    assert assembled["final_cases"].unresolved_questions == [
        "Confirm the fuzzy matching rule."
    ]


def test_reviewer_contract_rejects_score_field():
    with pytest.raises(ValueError):
        ReviewerAgentOutput.model_validate({"score": 98})


def test_nlu_normalizes_llm_identity_to_selected_operation(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    wrong_operation = operation.model_copy(
        update={"operation_id": "hallucinated-operation", "path": "/wrong-path"}
    )
    requirement = RequirementDocument(
        requirement_id="REQ-GET-ITEM-001",
        api=wrong_operation,
        evidence_refs=[
            RequirementEvidenceRef(
                evidence_id="evidence-not-in-snapshot",
                source_type="unknown",
                reference="unknown:reference",
            )
        ],
    )
    normalized_requirement = workflow._normalize_requirement(
        requirement,
        {
            "project_id": project_id,
            "operation": operation,
            "input_document_id": "reqdoc-test",
        },
    )
    assert normalized_requirement.api.operation_id == operation.operation_id
    assert normalized_requirement.api.path == operation.path
    assert normalized_requirement.source_document_id == "reqdoc-test"
    assert normalized_requirement.evidence_refs == []
    assert len(normalized_requirement.unresolved_questions) == 1

    points = TestPointCollection(
        requirement_id="hallucinated-requirement",
        requirement_version=9,
        points=[
            TestPoint(
                point_id="TP-1",
                requirement_id="hallucinated-requirement",
                title="Point",
                category="positive",
                action="Call the API",
                expected_result="The documented response is returned",
            )
        ],
    )
    normalized_points = workflow._normalize_test_points(points, normalized_requirement)
    assert normalized_points.requirement_id == normalized_requirement.requirement_id
    assert normalized_points.requirement_version == normalized_requirement.version
    assert normalized_points.points[0].requirement_id == normalized_requirement.requirement_id


def test_case_evidence_normalization_binds_assertions_to_known_test_point_evidence(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)
    evidence_id = "evidence-operation-get-item"
    point = TestPoint(
        point_id="TP-EVIDENCE",
        requirement_id="REQ-GET-ITEM-001",
        title="Evidence-backed point",
        category="positive",
        action="Call the API",
        expected_result="The documented response is returned",
        evidence_refs=[evidence_id],
    )
    case = TestCase(
        case_id="CASE-EVIDENCE",
        requirement_id="REQ-GET-ITEM-001",
        test_point_ids=[point.point_id],
        title="Evidence-backed case",
        category="positive",
        steps=["Send the request"],
        expected_behavior="The documented response is returned",
        request={"method": "GET", "path": "/items/1"},
        assertions=[
            Assertion(
                assertion_id="ASSERT-EVIDENCE",
                type="status_code",
                expected=200,
                evidence_refs=["reqdoc-unknown-id"],
            )
        ],
    )
    normalized = workflow._normalize_case_evidence(
        CaseSet(requirement_id="REQ-GET-ITEM-001", cases=[case]),
        {
            "project_id": project_id,
            "operation": operation,
            "evidence": EvidenceBundle(
                operation_id=operation.operation_id,
                facts=[
                    EvidenceFact(
                        evidence_id=evidence_id,
                        source_type="operation_yaml",
                        reference="operation:get-item",
                        fact="The operation is available.",
                    )
                ],
            ),
            "test_points": TestPointCollection(
                requirement_id="REQ-GET-ITEM-001",
                requirement_version=1,
                points=[point],
            ),
        },
    )
    assert normalized.cases[0].evidence_refs == [evidence_id]
    assert normalized.cases[0].assertions[0].evidence_refs == [evidence_id]


def test_invalid_designer_cases_become_clarification_gaps_instead_of_failing(tmp_path):
    workflow, project_id, operation, _ = _build_workflow(tmp_path)

    def invalid_designer_factory(payload):
        evidence_id = payload["evidence"].facts[0].evidence_id
        requirement_id = payload["requirement"].requirement_id
        supplement = payload.get("mode") == "supplement"
        point_id = "TP-MISSING" if supplement else "TP-VALID"
        case = TestCase(
            case_id="CASE-INVALID-SUPPLEMENT" if supplement else "CASE-INVALID-INITIAL",
            requirement_id=requirement_id,
            test_point_ids=[point_id],
            title="Invalid missing path parameter case",
            category="negative",
            steps=["Omit the required path parameter"],
            expected_behavior="The request is rejected",
            request={"method": "GET", "path": "/items/", "path_params": {}},
            assertions=[
                Assertion(
                    assertion_id=f"ASSERT-{point_id}",
                    type="status_code",
                    expected=400,
                    evidence_refs=[evidence_id],
                )
            ],
            evidence_refs=[evidence_id],
            source="reviewer_added" if supplement else "initial",
        )
        return DesignerAgentOutput(
            draft_cases=CaseSet(
                requirement_id=requirement_id,
                test_point_ids=[point_id],
                cases=[case],
            )
        )

    workflow.designer_agent = fake_agent(DesignerAgentOutput, invalid_designer_factory)
    result = _invoke_approved_workflow(
        workflow,
        {
            "workflow_id": "workflow-invalid-case-gap",
            "project_id": project_id,
            "operation_id": operation.operation_id,
            "events": [],
            "errors": [],
        },
    )

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["final_cases"].status == "NEEDS_CLARIFICATION"
    assert result["final_cases"].cases == []
    assert any(
        "Discarded invalid initial case CASE-INVALID-INITIAL" in gap
        for gap in result["final_cases"].remaining_gaps
    )
    assert any(
        "Discarded invalid reviewer_added case CASE-INVALID-SUPPLEMENT" in gap
        for gap in result["final_cases"].remaining_gaps
    )
