from __future__ import annotations

import asyncio

import httpx
import pytest

from app.assertions.engine import AssertionEvaluationError, evaluate_assertion, read_json_path
from app.executor.http import HttpExecutor
from app.models.cases import Assertion as CaseAssertion, RequestTemplate, TestCase as CaseModel
from app.models.projects import ProjectSettings
from app.models.execution import ExecutionResult, RunResult
from app.runs.store import RunStore


def execution_settings(base_url: str = "http://127.0.0.1") -> ProjectSettings:
    return ProjectSettings(
        sut_target={
            "base_url": base_url,
            "timeout_seconds": 3,
            "allow_redirects": False,
            "verify_tls": True,
        }
    )


def execution_case(assertions):
    return CaseModel(
        case_id="CASE-EXEC-1",
        requirement_id="REQ-EXEC-1",
        title="Execute item request",
        category="positive",
        steps=["Send request"],
        expected_behavior="A valid response is returned.",
        request={"method": "GET", "path": "/items/{item_id}", "path_params": {"item_id": 7}},
        assertions=assertions,
        evidence_refs=["E-1"],
    )


def test_json_path_and_assertions_cover_business_failure_and_expression():
    body = {"success": False, "errorMsg": "item not found", "data": {"items": [{"id": 7}]}}
    assert read_json_path(body, "$.data.items[0].id") == 7
    assert read_json_path({"data": [1, 2, 3]}, "$.data.length") == 3
    with pytest.raises(AssertionEvaluationError, match="must start with"):
        read_json_path(body, "data.items[0].id")
    status = evaluate_assertion(
        CaseAssertion(assertion_id="A-status", type="status_code", expected=200),
        status_code=200,
        headers={},
        body=body,
        duration_ms=12,
    )
    business = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-business",
            type="json_value",
            path="$.success",
            expected=True,
        ),
        status_code=200,
        headers={},
        body=body,
        duration_ms=12,
    )
    response_time = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-time",
            type="response_time_ms",
            expected=20,
            operator="<=",
        ),
        status_code=200,
        headers={},
        body=body,
        duration_ms=12,
    )
    assert status.passed is True
    assert business.passed is False
    assert response_time.passed is True


def test_assertions_accept_llm_operator_aliases_and_ranges():
    equality = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-eq",
            type="json_value",
            path="$.success",
            expected=True,
            operator="eq",
        ),
        status_code=200,
        headers={},
        body={"success": True},
        duration_ms=1,
    )
    status_range = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-between",
            type="status_code",
            expected=[400, 499],
            operator="between",
        ),
        status_code=404,
        headers={},
        body={},
        duration_ms=1,
    )

    assert equality.passed is True
    assert status_range.passed is True


def test_json_type_and_response_schema_are_structural():
    boolean_as_integer = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-type",
            type="json_type",
            path="$.success",
            expected="integer",
        ),
        status_code=200,
        headers={},
        body={"success": True},
        duration_ms=1,
    )
    schema = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-schema",
            type="response_schema",
            expected={
                "type": "object",
                "required": ["success"],
                "properties": {"success": {"type": "boolean"}},
            },
        ),
        status_code=200,
        headers={},
        body={"success": True},
        duration_ms=1,
    )
    assert boolean_as_integer.passed is False
    assert schema.passed is True


def test_json_exists_can_assert_a_required_field_is_absent():
    assertion = CaseAssertion(
        assertion_id="A-no-password",
        type="json_exists",
        path="$.password",
        expected=False,
    )

    absent = evaluate_assertion(
        assertion,
        status_code=200,
        headers={},
        body={"id": 1},
        duration_ms=1,
    )
    present = evaluate_assertion(
        assertion,
        status_code=200,
        headers={},
        body={"id": 1, "password": "masked"},
        duration_ms=1,
    )

    assert absent.passed is True
    assert absent.actual is False
    assert present.passed is False
    assert present.actual is True


def test_json_array_sorted_checks_primary_and_tie_breaker_fields():
    assertion = CaseAssertion(
        assertion_id="A-sort",
        type="json_array_sorted",
        path="$.data",
        expected={
            "fields": [
                {"path": "$.liked", "order": "desc"},
                {"path": "$.id", "order": "desc"},
            ]
        },
    )
    accepted = evaluate_assertion(
        assertion,
        status_code=200,
        headers={},
        body={"data": [{"liked": True, "id": 9}, {"liked": True, "id": 7}, {"liked": False, "id": 8}]},
        duration_ms=1,
    )
    rejected = evaluate_assertion(
        assertion,
        status_code=200,
        headers={},
        body={"data": [{"liked": True, "id": 7}, {"liked": True, "id": 9}]},
        duration_ms=1,
    )

    assert accepted.passed is True
    assert rejected.passed is False


def test_response_schema_can_reject_undocumented_object_fields():
    assertion = CaseAssertion(
        assertion_id="A-strict-schema",
        type="response_schema",
        expected={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["success", "data"],
            "additionalProperties": False,
        },
    )
    accepted = evaluate_assertion(
        assertion,
        status_code=200,
        headers={},
        body={"success": True, "data": [{"id": 1}]},
        duration_ms=1,
    )
    rejected = evaluate_assertion(
        assertion,
        status_code=200,
        headers={},
        body={"success": True, "data": [{"id": 1, "createTime": "unexpected"}]},
        duration_ms=1,
    )

    assert accepted.passed is True
    assert rejected.passed is False


def test_response_schema_can_validate_a_json_path_node():
    result = evaluate_assertion(
        CaseAssertion(
            assertion_id="A-schema-path",
            type="response_schema",
            path="$.data",
            expected={
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
            },
        ),
        status_code=200,
        headers={},
        body={"success": True, "data": [{"id": 1}]},
        duration_ms=1,
    )

    assert result.passed is True
    assert result.actual == [{"id": 1}]


def test_http_executor_renders_path_and_records_assertions():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1/items/7"
        return httpx.Response(
            200,
            json={"success": True, "data": {"id": 7}},
            headers={"X-Trace": "trace-1"},
            request=request,
        )

    case = execution_case(
        [
            {"assertion_id": "A-status", "type": "status_code", "expected": 200, "evidence_refs": ["E-1"]},
            {"assertion_id": "A-id", "type": "json_value", "path": "$.data.id", "expected": 7, "evidence_refs": ["E-1"]},
            {"assertion_id": "A-header", "type": "header_value", "path": "x-trace", "expected": "trace-1", "evidence_refs": ["E-1"]},
        ]
    )
    result = asyncio.run(
        HttpExecutor(transport=httpx.MockTransport(handler)).execute(case, execution_settings())
    )
    assert result.status == "passed"
    assert result.status_code == 200
    assert result.case_title == "Execute item request"
    assert len(result.assertion_results) == 3
    assert result.assertion_results[1].type == "json_value"
    assert result.assertion_results[1].path == "$.data.id"
    assert result.assertion_results[1].evidence_refs == ["E-1"]
    assert result.response_body["data"]["id"] == 7


def test_http_executor_rejects_unresolved_paths_and_remote_targets():
    unresolved = execution_case(
        [{"assertion_id": "A-status", "type": "status_code", "expected": 200, "evidence_refs": ["E-1"]}]
    ).model_copy(update={"request": RequestTemplate(method="GET", path="/items/{missing}")})
    unresolved_result = asyncio.run(
        HttpExecutor(transport=httpx.MockTransport(lambda request: httpx.Response(200))).execute(
            unresolved, execution_settings()
        )
    )
    assert unresolved_result.status == "error"
    assert unresolved_result.error_category == "transport_error"

    remote_result = asyncio.run(
        HttpExecutor(transport=httpx.MockTransport(lambda request: httpx.Response(200))).execute(
            execution_case(
                [{"assertion_id": "A", "type": "status_code", "expected": 200, "evidence_refs": ["E-1"]}]
            ),
            execution_settings("https://external.invalid"),
        )
    )
    assert remote_result.status == "error"
    assert remote_result.error_category == "transport_error"


def test_http_executor_revalidates_redirect_targets():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request.url.host == "127.0.0.1":
            return httpx.Response(
                302,
                headers={"Location": "http://metadata.invalid/latest"},
                request=request,
            )
        pytest.fail("redirect target must be rejected before transport")

    settings = execution_settings().model_copy(
        update={
            "sut_target": execution_settings().sut_target.model_copy(
                update={"allow_redirects": True}
            )
        }
    )
    result = asyncio.run(
        HttpExecutor(transport=httpx.MockTransport(handler)).execute(
            execution_case(
                [
                    {
                        "assertion_id": "A-status",
                        "type": "status_code",
                        "expected": 200,
                        "evidence_refs": ["E-1"],
                    }
                ]
            ),
            settings,
        )
    )

    assert request_count == 1
    assert result.status == "error"
    assert result.error_category == "transport_error"
    assert result.error_message == "remote targets are disabled"


def test_http_executor_rejects_credentials_in_target_url():
    executor = HttpExecutor()

    with pytest.raises(ValueError, match="must not contain credentials"):
        executor.validate_target("http://user:secret@127.0.0.1:8080")


def test_http_executor_redacts_secrets_after_assertion_evaluation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "visible-to-assertions",
                "nested": {"password": "do-not-store", "safe": "kept"},
            },
            headers={"Set-Cookie": "session=do-not-store", "X-Trace": "trace-1"},
            request=request,
        )

    result = asyncio.run(
        HttpExecutor(transport=httpx.MockTransport(handler)).execute(
            execution_case(
                [
                    {
                        "assertion_id": "A-token",
                        "type": "json_value",
                        "path": "$.access_token",
                        "expected": "visible-to-assertions",
                        "evidence_refs": ["E-1"],
                    }
                ]
            ),
            execution_settings(),
        )
    )

    assert result.status == "passed"
    assert result.response_headers["set-cookie"] == "[REDACTED]"
    assert result.response_headers["x-trace"] == "trace-1"
    assert result.response_body == {
        "access_token": "[REDACTED]",
        "nested": {"password": "[REDACTED]", "safe": "kept"},
    }


def test_http_executor_allows_case_query_parameters():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == "e2e-no-matching-item"
        return httpx.Response(200, json={"success": True, "data": []}, request=request)

    case = execution_case(
        [
            {
                "assertion_id": "A-status",
                "type": "status_code",
                "expected": 200,
                "evidence_refs": ["E-1"],
            }
        ]
    ).model_copy(
        update={
            "request": RequestTemplate(
                method="GET",
                path="/items/of/name",
                query_params={"name": "e2e-no-matching-item"},
            )
        }
    )

    result = asyncio.run(
        HttpExecutor(transport=httpx.MockTransport(handler)).execute(
            case,
            execution_settings(),
        )
    )

    assert result.status == "passed"
    assert result.status_code == 200


def test_run_store_round_trip_is_process_local(tmp_path):
    run = RunResult(
        run_id="run-phase6",
        project_id="project-1",
        requirement_id="REQ-1",
        results=[
            ExecutionResult(
                result_id="result-1",
                case_id="CASE-1",
                requirement_id="REQ-1",
                status="passed",
                method="GET",
                url="http://127.0.0.1/items/1",
            )
        ],
        passed_count=1,
        failed_count=0,
        error_count=0,
    )
    store = RunStore(tmp_path, "project-1")
    store.save(run)
    restored = RunStore(tmp_path, "project-1").get("run-phase6")
    assert restored is not None
    assert restored.results[0].status == "passed"
    assert not (tmp_path / "projects" / "project-1" / "runs").exists()
