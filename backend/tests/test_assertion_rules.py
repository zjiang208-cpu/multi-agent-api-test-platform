from app.cases.validator import validate_case
from app.models.contracts import OperationContract
from app.models.testpoints import TestPoint
from app.workflow.assertion_rules import enrich_case_assertions
from app.models.cases import Assertion, TestCase


def _operation() -> OperationContract:
    return OperationContract(
        operation_id="get-voucher-id",
        method="GET",
        path="/voucher/{id}",
        parameters=[
            {
                "name": "id",
                "location": "path",
                "required": True,
                "type": "integer",
            }
        ],
        responses=[{"status_code": 200}],
    )


def test_enrich_case_assertions_keeps_existing_and_adds_basic_response_contract():
    point = TestPoint(
        point_id="TP-INVALID-BODY",
        requirement_id="REQ-1",
        title="非法请求体",
        category="negative",
        action="发送请求",
        expected_result="返回 HTTP 400，success=false，errorMsg='Request body is invalid'。",
        evidence_refs=["E-1"],
    )
    case = TestCase(
        case_id="CASE-1",
        requirement_id="REQ-1",
        test_point_ids=[point.point_id],
        title=point.title,
        category=point.category,
        steps=[point.action],
        expected_behavior=point.expected_result,
        request={"method": "GET", "path": "/voucher/{id}", "path_params": {"id": 0}},
        assertions=[
            Assertion(
                assertion_id="ASSERT-STATUS",
                type="status_code",
                expected=400,
                operator="eq",
                evidence_refs=["E-1"],
            )
        ],
        evidence_refs=["E-1"],
    )

    enriched = enrich_case_assertions(case, [point])
    signatures = {
        (item.type, item.path, item.expected)
        for item in enriched.assertions
    }
    assert ("status_code", None, 400) in signatures
    assert ("json_value", "$.success", False) in signatures
    assert ("json_value", "$.errorMsg", "Request body is invalid") in signatures


def test_enrich_case_assertions_supports_structured_expected_values():
    point = TestPoint(
        point_id="TP-LIST-CONTRACT",
        requirement_id="REQ-1",
        title="查询列表",
        category="positive",
        action="查询列表",
        expected_result="返回 HTTP 200。",
        evidence_refs=["E-1"],
    )
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
    contains = [{"id": 1}]
    case = TestCase(
        case_id="CASE-LIST-CONTRACT",
        requirement_id="REQ-1",
        test_point_ids=[point.point_id],
        title=point.title,
        category=point.category,
        steps=[point.action],
        expected_behavior=point.expected_result,
        request={"method": "GET", "path": "/voucher/{id}", "path_params": {"id": 1}},
        assertions=[
            Assertion(
                assertion_id="ASSERT-SCHEMA",
                type="response_schema",
                expected=schema,
                evidence_refs=["E-1"],
            ),
            Assertion(
                assertion_id="ASSERT-CONTAINS",
                type="json_contains",
                path="$.data",
                expected=contains,
                evidence_refs=["E-1"],
            ),
        ],
        evidence_refs=["E-1"],
    )

    enriched = enrich_case_assertions(case, [point])

    assert len(enriched.assertions) == 3
    assert enriched.assertions[0].expected == schema
    assert enriched.assertions[1].expected == contains
    assert any(
        assertion.type == "status_code" and assertion.expected == 200
        for assertion in enriched.assertions
    )


def test_enrich_case_assertions_normalizes_declared_fields_and_empty_arrays():
    point = TestPoint(
        point_id="TP-CONTRACT-EMPTY",
        requirement_id="REQ-1",
        title="响应不返回创建时间和更新时间，空数组时仍返回成功响应",
        category="contract",
        action="查询列表",
        expected_result="返回 HTTP 200，success=true，data 为空数组。",
        evidence_refs=["E-1"],
    )
    case = TestCase(
        case_id="CASE-CONTRACT-EMPTY",
        requirement_id="REQ-1",
        test_point_ids=[point.point_id],
        title=point.title,
        category=point.category,
        steps=[point.action],
        expected_behavior=point.expected_result,
        request={"method": "GET", "path": "/voucher/{id}", "path_params": {"id": 1}},
        assertions=[
            Assertion(
                assertion_id="ASSERT-CREATE-ABSENT",
                type="json_exists",
                path="$.data[0].create_time",
                expected=False,
                evidence_refs=["E-1"],
            ),
            Assertion(
                assertion_id="ASSERT-CREATE-CONTRADICTORY",
                type="json_exists",
                path="$.data.create_time",
                expected=True,
                evidence_refs=["E-1"],
            ),
        ],
        evidence_refs=["E-1"],
    )

    enriched = enrich_case_assertions(case, [point])
    signatures = {
        (item.type, item.path, item.expected)
        for item in enriched.assertions
    }

    assert ("json_exists", "$.data[0].createTime", False) in signatures
    assert ("json_exists", "$.data[0].updateTime", False) in signatures
    assert ("json_type", "$.data", "array") in signatures
    assert ("json_value", "$.data.length", 0) in signatures
    assert ("json_exists", "$.data.createTime", True) not in signatures
    assert not any("create_time" in (item.path or "") for item in enriched.assertions)


def test_ready_case_cannot_hide_unresolved_request_value():
    point = TestPoint(
        point_id="TP-1",
        requirement_id="REQ-1",
        title="成功查询",
        category="positive",
        action="查询资源",
        expected_result="返回 HTTP 200。",
        evidence_refs=["E-1"],
    )
    case = TestCase(
        case_id="CASE-READY",
        requirement_id="REQ-1",
        test_point_ids=[point.point_id],
        title=point.title,
        category=point.category,
        steps=[point.action],
        expected_behavior=point.expected_result,
        request={
            "method": "GET",
            "path": "/voucher/{id}",
            "path_params": {"id": "$UNRESOLVED[parameter:id]"},
        },
        assertions=[
            Assertion(
                assertion_id="ASSERT-STATUS",
                type="status_code",
                expected=200,
                evidence_refs=["E-1"],
            )
        ],
        evidence_refs=["E-1"],
    )

    errors = validate_case(
        case,
        known_test_points={point.point_id},
        known_evidence={"E-1"},
        operation=_operation(),
    )
    assert "path parameters contain unresolved placeholders" in errors
