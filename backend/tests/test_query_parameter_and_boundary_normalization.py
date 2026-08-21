from __future__ import annotations

import hashlib

from app.models.cases import Assertion, RequestTemplate, TestCase
from app.models.documents import StoredRequirementDocument
from app.models.evidence import EvidenceBundle
from app.models.testpoints import TestPoint, TestPointCollection
from app.requirements.api_discovery import ApiDiscoveryService
from app.workflow.case_rules import CaseRulesMixin


def test_markdown_query_parameter_table_is_added_to_operation_contract():
    content = """
# 按类型分页查询商铺

## 1. 基本信息

| 项目 | 内容 |
|---|---|
| 接口编号 | `SHOP-004` |
| 方法 | `GET` |
| 路径 | `/shop/of/type` |

## 2. 查询参数

| 参数 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `typeId` | Integer | 是 | 无 | 大于0 |
| `current` | Integer | 否 | `1` | 大于0 |
""".strip()
    document = StoredRequirementDocument(
        document_id="doc-shop-004",
        filename="list-shops-by-type.md",
        format="md",
        detected_kind="requirement_document",
        media_type="text/markdown",
        content=content,
        char_count=len(content),
        line_count=content.count("\n") + 1,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )

    operation = ApiDiscoveryService().discover(document)[0]

    assert [(item.name, item.location, item.required) for item in operation.parameters] == [
        ("typeId", "query", True),
        ("current", "query", False),
    ]
    assert operation.parameters[0].schema_type == "integer"
    assert operation.parameters[0].constraints == {"minimum": 0, "exclusiveMinimum": True}


def test_case_normalization_corrects_string_boundary_length_without_interface_rules():
    point = TestPoint(
        point_id="TP-DEMO-NAME-32",
        requirement_id="REQ-DEMO",
        title="name 长度为 32 字符时成功",
        category="boundary",
        action="请求体 name 为恰好 32 个字符的字符串。",
        expected_result="name 长度等于 32 时允许提交。",
    )
    reversed_point = TestPoint(
        point_id="TP-DEMO-ICON-255",
        requirement_id="REQ-DEMO",
        title="长度为 255 的 icon 字段",
        category="boundary",
        action="请求体包含长度为 255 的 icon 字段。",
        expected_result="icon 长度等于 255。",
    )
    case = TestCase(
        case_id="CASE-DEMO-NAME-32",
        requirement_id="REQ-DEMO",
        test_point_ids=[point.point_id, reversed_point.point_id],
        title="name 边界值",
        category="boundary",
        steps=["发送请求"],
        expected_behavior="请求成功。",
        request=RequestTemplate(
            method="POST",
            path="/demo",
            body={"name": "too-short", "icon": "i"},
        ),
        assertions=[
            Assertion(
                assertion_id="ASSERT-DEMO-NAME-32",
                type="status_code",
                expected=200,
            )
        ],
    )

    normalized = CaseRulesMixin._normalize_case_list(
        [case],
        {
            "evidence": EvidenceBundle(operation_id="demo"),
            "test_points": TestPointCollection(
                requirement_id="REQ-DEMO",
                requirement_version=1,
                points=[point, reversed_point],
            ),
        },
    )[0]

    assert len(normalized.request.body["name"]) == 32
    assert normalized.request.body["name"].startswith("too-short")
    assert len(normalized.request.body["icon"]) == 255
