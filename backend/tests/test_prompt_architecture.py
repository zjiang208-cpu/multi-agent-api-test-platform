from __future__ import annotations

from app.cases.validator import validate_case
from app.models.cases import Assertion, TestCase as CaseModel
from app.models.contracts import OperationContract
from app.workflow.models import ReviewerAgentOutput
from app.workflow.prompt_registry import load_prompt, prompt_manifest


def test_three_api_prompt_files_are_independently_versioned_and_hashed():
    prompts = {name: load_prompt(name) for name in ("nlu", "designer", "reviewer")}
    assert {prompt.definition.name for prompt in prompts.values()} == {
        "nlu",
        "designer",
        "reviewer",
    }
    assert {name: prompt.definition.version for name, prompt in prompts.items()} == {
        "nlu": "1.5.4",
        "designer": "1.5.6",
        "reviewer": "1.3.6",
    }
    assert all(len(prompt.sha256) == 64 for prompt in prompts.values())
    assert len({prompt.source_path for prompt in prompts.values()}) == 3
    assert prompt_manifest()["reviewer_prompt_version"] == "1.3.6"
    assert prompts["designer"].definition.retry.max_attempts == 2
    assert prompts["reviewer"].definition.retry.max_attempts == 1
    assert prompts["nlu"].definition.retry.max_attempts == 2
    assert len(prompts["nlu"].definition.few_shot_examples) == 2
    assert len(prompts["designer"].definition.few_shot_examples) == 2
    assert "Few-Shot 示例" in prompts["designer"].system_prompt
    assert "资深的接口测试需求分析师兼测试开发工程师" in prompts["nlu"].system_prompt
    assert "HTTP API 黑盒/契约辅助测试" in prompts["nlu"].system_prompt
    assert "证据优先级固定为" in prompts["nlu"].system_prompt
    assert "source_document 可能包含多份文档和多个接口" in prompts["nlu"].system_prompt
    assert "没有需求文档时" in prompts["nlu"].system_prompt
    assert "文档明确“不使用 Bearer”时不得补写 Bearer" in prompts["nlu"].system_prompt
    assert "auth_protocol" in prompts["nlu"].system_prompt
    assert "$AUTH_FIXTURE[...]" in prompts["nlu"].system_prompt
    assert "$AUTH_FIXTURE[...]" in prompts["designer"].system_prompt
    assert "资深的接口自动化测试开发工程师" in prompts["designer"].system_prompt
    assert "输入优先级固定为" in prompts["designer"].system_prompt
    assert "过期/不存在 Token" in prompts["designer"].system_prompt
    assert "无法取得具体值时不生成该 Case" in prompts["designer"].system_prompt
    assert "## 用例设计方法论" in prompts["designer"].system_prompt
    assert "显式验证点优先映射" in prompts["designer"].system_prompt
    assert "专项场景触发规则" in prompts["designer"].system_prompt
    assert "遗漏高风险场景补齐" in prompts["designer"].system_prompt
    assert "明确值与对象保真" in prompts["designer"].system_prompt
    assert "输出前自检闸门" in prompts["designer"].system_prompt
    assert "### Operation 锚定与证据优先级" in prompts["nlu"].system_prompt
    assert "### Requirement 与 Test Point 映射" in prompts["nlu"].system_prompt
    assert "### 一、用例范围与标识" in prompts["designer"].system_prompt
    for prompt in prompts.values():
        assert prompt.definition.rule_sections
        assert prompt.definition.quality_sections
        assert prompt.definition.rules == []
        assert prompt.definition.quality_checks == []
    assert "status=unknown" in prompts["nlu"].system_prompt
    assert "支持使用 json_exists=true/false" in prompts["nlu"].system_prompt
    assert "不得通过删除路径占位符" in prompts["nlu"].system_prompt
    assert "不得把 /resource/{id} 改成 /resource/" in prompts["designer"].system_prompt
    assert "不得为它生成 suggested_case_specs" in prompts["reviewer"].system_prompt
    assert "Test Point → Case → Assertion" in prompts["reviewer"].system_prompt
    assert "审查结论到 Schema 字段的映射" in prompts["reviewer"].system_prompt
    assert "auth_protocol 明确无 Bearer" in prompts["reviewer"].system_prompt
    assert "suggested_case_specs 是给 Designer 的补例规格" in prompts["reviewer"].system_prompt
    assert "资深的接口自动化测试审查工程师" in prompts["reviewer"].system_prompt
    for prompt in prompts.values():
        assert "JSON.parse" in prompt.system_prompt
        assert "禁止 Markdown 代码块" in prompt.system_prompt
        assert "严格匹配 Schema" in prompt.system_prompt


def test_reviewer_schema_contains_findings_but_not_complete_supplemental_cases():
    properties = ReviewerAgentOutput.model_json_schema()["properties"]
    assert "suggested_case_specs" in properties
    assert "semantic_gaps" in properties
    assert "supplemental_cases" not in properties
    restored = ReviewerAgentOutput.model_validate({"supplemental_cases": []})
    assert "supplemental_cases" not in restored.model_dump()


def test_operation_and_side_effect_invariants_are_program_enforced():
    operation = OperationContract(
        operation_id="update-item",
        method="POST",
        path="/items/{item_id}",
        parameters=[
            {"name": "item_id", "location": "path", "required": True},
            {"name": "locale", "location": "query", "required": True},
            {"name": "X-Tenant", "location": "header", "required": True},
        ],
        responses=[{"status_code": 200}],
    )
    case = CaseModel(
        case_id="CASE-UPDATE",
        requirement_id="REQ-UPDATE",
        test_point_ids=["TP-UPDATE"],
        title="Update item",
        category="positive",
        steps=["Send the documented update request"],
        expected_behavior="The documented update response is returned.",
        request={
            "method": "POST",
            "path": "/items/{item_id}",
            "path_params": {"item_id": 7},
            "query_params": {"locale": "zh-CN"},
            "headers": {"X-Tenant": "tenant-a"},
            "body": {"name": "updated"},
        },
        assertions=[
            Assertion(
                assertion_id="ASSERT-STATUS",
                type="status_code",
                expected=200,
                evidence_refs=["E-UPDATE"],
            )
        ],
        evidence_refs=["E-UPDATE"],
        side_effect=True,
        side_effect_note="Updates the selected item.",
    )
    assert validate_case(
        case,
        known_test_points={"TP-UPDATE"},
        known_evidence={"E-UPDATE"},
        operation=operation,
    ) == []

    unsafe = case.model_copy(
        update={
            "request": case.request.model_copy(update={"method": "GET", "path": "/other"}),
            "side_effect": False,
            "side_effect_note": None,
        }
    )
    errors = validate_case(
        unsafe,
        known_test_points={"TP-UPDATE"},
        known_evidence={"E-UPDATE"},
        operation=operation,
    )
    assert any("does not match operation method" in error for error in errors)
    assert any("does not match operation path" in error for error in errors)

    unmarked_side_effect = case.model_copy(
        update={"side_effect": False, "side_effect_note": None}
    )
    side_effect_errors = validate_case(
        unmarked_side_effect,
        known_test_points={"TP-UPDATE"},
        known_evidence={"E-UPDATE"},
        operation=operation,
    )
    assert any("must be marked as side-effecting" in error for error in side_effect_errors)


def test_validator_accepts_non_existence_and_rejects_unsupported_jsonpath_assertions():
    operation = OperationContract(
        operation_id="get-item",
        method="GET",
        path="/items",
        responses=[{"status_code": 200}],
    )
    case = CaseModel(
        case_id="CASE-UNSUPPORTED-JSON",
        requirement_id="REQ-ITEM",
        test_point_ids=["TP-ITEM"],
        title="Unsupported JSON assertions",
        category="contract",
        steps=["Send the request"],
        expected_behavior="The response follows the contract.",
        request={"method": "GET", "path": "/items"},
        assertions=[
            Assertion(
                assertion_id="ASSERT-NOT-EXISTS",
                type="json_exists",
                path="$.data.secret",
                expected=False,
                evidence_refs=["E-CONTRACT"],
            ),
            Assertion(
                assertion_id="ASSERT-WILDCARD",
                type="json_type",
                path="$.data[*].id",
                expected="integer",
                evidence_refs=["E-CONTRACT"],
            ),
        ],
        evidence_refs=["E-CONTRACT"],
    )

    errors = validate_case(
        case,
        known_test_points={"TP-ITEM"},
        known_evidence={"E-CONTRACT"},
        operation=operation,
    )

    assert not any("json_exists only supports" in error for error in errors)
    assert any("unsupported path expression" in error for error in errors)
