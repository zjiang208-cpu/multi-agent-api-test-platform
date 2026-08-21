from __future__ import annotations

from pathlib import Path

import yaml

from evals.dataset import enrich_manifest_with_catalog
from evals.baseline_ground_truth import BASELINE_POINTS
from evals.fixture_audit import audit_fixture_requirements
from evals.models import EvalDatasetManifest, GroundTruthOperation, GroundTruthPoint
from evals.requirements_catalog import build_catalog, parse_requirement_file


def _write_document(root: Path, relative: str, *, interface_id: str, method: str, path: str, title: str = "接口") -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""# {title}

## 1. 基本信息

| 项目 | 内容 |
|---|---|
| 接口编号 | `{interface_id}` |
| 方法 | `{method}` |
| 路径 | `{path}` |
| 权限 | 登录 |

## 2. 请求参数

`id` 必填且大于0。

## 3. 成功响应

返回成功数据。

## 4. 业务规则

重复请求必须幂等。

## 5. 失败场景

资源不存在或参数非法。

## 6. 验收标准

- 正常请求成功。
""",
        encoding="utf-8",
    )


def test_parse_requirement_file_extracts_contract_and_candidate_points(tmp_path: Path):
    _write_document(
        tmp_path,
        "shop/get-shop.md",
        interface_id="TEST-001",
        method="GET",
        path="/shop/{id}",
        title="查询商铺详情",
    )

    operation = parse_requirement_file(tmp_path / "shop/get-shop.md", tmp_path)

    assert operation["operation_id"] == "TEST-001"
    assert operation["method"] == "GET"
    assert operation["path"] == "/shop/{id}"
    assert operation["source_reference"] == "shop/get-shop.md"
    assert "验收标准" not in (operation["notes"] or "")
    assert "失败场景" not in (operation["notes"] or "")
    assert {point["category"] for point in operation["points"]} == {
        "positive",
        "auth",
        "boundary",
        "negative",
        "contract",
    }
    assert operation["metadata"]["current_contract"] is False


def test_parse_requirement_file_uses_reviewed_points_for_baseline_operation(tmp_path: Path):
    _write_document(
        tmp_path,
        "shop/get-shop.md",
        interface_id="SHOP-001",
        method="GET",
        path="/shop/{id}",
    )

    operation = parse_requirement_file(tmp_path / "shop/get-shop.md", tmp_path)

    assert operation["metadata"]["baseline_operation_id"] == "get-shop-id"
    assert [point["point_id"] for point in operation["points"]] == [
        "SHOP-001-POSITIVE",
        "SHOP-001-BOUNDARY-ID",
        "SHOP-001-BOUNDARY-MIN",
        "SHOP-001-NEGATIVE-TYPE-MISMATCH",
        "SHOP-001-NEGATIVE-NOT-FOUND",
        "SHOP-001-CONTRACT-CACHE-MISS",
        "SHOP-001-CONTRACT-CACHE-HIT",
        "SHOP-001-CONTRACT-NULL-CACHE",
    ]


def test_parse_requirement_file_normalizes_current_legacy_method(tmp_path: Path):
    _write_document(
        tmp_path,
        "upload/delete-blog-image.md",
        interface_id="UPLOAD-003",
        method="GET（当前实现）",
        path="/upload/blog/delete",
        title="删除笔记图片",
    )

    operation = parse_requirement_file(tmp_path / "upload/delete-blog-image.md", tmp_path)

    assert operation["method"] == "GET"
    assert operation["metadata"]["legacy_contract"] is True
    assert operation["metadata"]["compatibility_reference"] is False
    assert "当前实现" in (operation["notes"] or "")


def test_build_catalog_audits_duplicate_ids_and_numbering_gaps(tmp_path: Path):
    _write_document(tmp_path, "shop/a.md", interface_id="SHOP-001", method="GET", path="/shop/a")
    _write_document(tmp_path, "shop/b.md", interface_id="SHOP-001", method="DELETE", path="/shop/b")
    _write_document(tmp_path, "shop/c.md", interface_id="SHOP-003", method="PUT", path="/shop/c")

    catalog = build_catalog(tmp_path)

    assert catalog["audit"]["total_documents"] == 3
    assert catalog["audit"]["unique_interface_ids"] == 2
    assert catalog["audit"]["duplicate_interface_ids"] == ["SHOP-001"]
    issue_types = {issue["type"] for issue in catalog["audit"]["issues"]}
    assert "duplicate_interface_id" in issue_types
    assert "numbering_gap" in issue_types


def test_build_catalog_normalizes_confirmed_user_id_and_upload_lifecycle(tmp_path: Path):
    _write_document(
        tmp_path,
        "user/delete-current-user.md",
        interface_id="USER-007",
        method="DELETE",
        path="/user/me",
    )
    _write_document(
        tmp_path,
        "upload/delete-blog-image.md",
        interface_id="UPLOAD-003",
        method="GET（当前实现）",
        path="/upload/blog/delete",
    )
    _write_document(
        tmp_path,
        "upload/delete-blog-image-delete.md",
        interface_id="UPLOAD-005",
        method="DELETE",
        path="/upload/blog?name={path}",
    )

    catalog = build_catalog(tmp_path)
    operations = {operation["source_reference"]: operation for operation in catalog["operations"]}

    assert operations["user/delete-current-user.md"]["operation_id"] == "USER-009"
    assert operations["upload/delete-blog-image.md"]["metadata"]["contract_role"] == "observed_legacy"
    assert operations["upload/delete-blog-image-delete.md"]["metadata"]["contract_role"] == "target_recommended"
    assert catalog["audit"]["scope_exclusions"][0]["interface_ids"] == ["USER-001", "USER-002"]


def test_enrich_manifest_with_catalog_keeps_historical_operation_ids(tmp_path: Path):
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "operations": [
                    {
                        "operation_id": "SHOP-001",
                        "source_reference": "shop/get-shop.md",
                        "points": [
                            {
                                "point_id": "SHOP-001-POSITIVE",
                                "description": "正常查询",
                                "category": "positive",
                            }
                        ],
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    manifest = EvalDatasetManifest(
        dataset_id="baseline_v1",
        version="1.0.0",
        source="local",
        operations=[
            GroundTruthOperation(
                operation_id="get-shop-id",
                source_reference="shop/get-shop.md",
            )
        ],
    )

    enriched = enrich_manifest_with_catalog(manifest, catalog_path)

    assert enriched.annotation_status == "draft"
    assert enriched.operations[0].operation_id == "get-shop-id"
    assert enriched.operations[0].annotation_status == "draft"
    assert enriched.operations[0].points[0].point_id == "SHOP-001-POSITIVE"


def test_reviewed_array_sort_assertions_follow_executor_contract():
    sort_assertions = [
        assertion
        for points in BASELINE_POINTS.values()
        for point in points
        for assertion in point["required_assertions"]
        if assertion["type"] == "json_array_sorted"
    ]

    assert len(sort_assertions) == 3
    assert all(
        isinstance(assertion["expected"], dict)
        and isinstance(assertion["expected"].get("fields"), list)
        and assertion["expected"]["fields"]
        for assertion in sort_assertions
    )


def test_reviewed_points_formalize_observation_mode_and_preconditions():
    observation_points = [
        point
        for points in BASELINE_POINTS.values()
        for point in points
        if point["verification_mode"] == "observation"
    ]

    assert observation_points
    assert all(point.get("observation_requirements") for point in observation_points)
    assert all(point.get("preconditions") for point in observation_points)

    typed_point = GroundTruthPoint.model_validate(observation_points[0])
    assert typed_point.verification_mode == "observation"
    assert typed_point.observation_requirements
    assert typed_point.preconditions


def test_reviewed_preconditions_have_safe_fixture_plans():
    points = [point for points in BASELINE_POINTS.values() for point in points]
    points_with_preconditions = [point for point in points if point.get("preconditions")]

    assert points_with_preconditions
    assert all(point.get("fixture_requirements") for point in points_with_preconditions)

    typed_points = [GroundTruthPoint.model_validate(point) for point in points]
    requirements = [requirement for point in typed_points for requirement in point.fixture_requirements]
    local_tokens = [requirement.token for requirement in requirements if requirement.resolution == "local_token"]

    assert requirements
    assert local_tokens
    assert all(token.startswith(("$DB_FIXTURE[", "$AUTH_FIXTURE[")) for token in local_tokens)
    assert any(token == "$DB_FIXTURE[existing:tb_shop:id]" for token in local_tokens)
    assert any(token == "$AUTH_FIXTURE[nonexistent:token]" for token in local_tokens)


def test_fixture_audit_is_read_only_and_reports_plan_breakdown():
    manifest = EvalDatasetManifest(
        dataset_id="fixture-audit",
        version="1.0.0",
        source="test",
        annotation_status="draft",
        operations=[
            GroundTruthOperation(
                operation_id="demo",
                annotation_status="draft",
                points=[
                    GroundTruthPoint(
                        point_id="DEMO-001",
                        description="准备一个已存在资源。",
                        category="positive",
                        preconditions=["准备一个已存在资源。"],
                        fixture_requirements=[
                            {
                                "reference": "existing-resource",
                                "kind": "database",
                                "description": "使用本地数据库 Fixture 解析已存在资源。",
                                "resolution": "local_token",
                                "token": "$DB_FIXTURE[existing:tb_demo:id]",
                            },
                            {
                                "reference": "cache-state",
                                "kind": "cache",
                                "description": "人工准备缓存命中状态。",
                                "resolution": "manual_setup",
                            },
                        ],
                    )
                ],
            )
        ],
    )

    audit = audit_fixture_requirements(manifest)

    assert audit["status"] == "ready"
    assert audit["fixture_requirements"] == 2
    assert audit["by_resolution"] == {"local_token": 1, "manual_setup": 1}
    assert audit["by_kind"] == {"cache": 1, "database": 1}
    assert audit["structural_issues"] == []
    assert audit["local_tokens"][0]["token"] == "$DB_FIXTURE[existing:tb_demo:id]"
    assert audit["manual_items"][0]["reference"] == "cache-state"


def test_fixture_audit_marks_incomplete_observation_plans_for_review():
    manifest = EvalDatasetManifest(
        dataset_id="fixture-audit-incomplete",
        version="1.0.0",
        source="test",
        operations=[
            GroundTruthOperation(
                operation_id="demo",
                points=[
                    GroundTruthPoint(
                        point_id="DEMO-OBS-001",
                        description="需要人工观察的点。",
                        category="contract",
                        verification_mode="observation",
                        preconditions=["准备观察所需状态。"],
                    )
                ],
            )
        ],
    )

    audit = audit_fixture_requirements(manifest)

    assert audit["status"] == "needs_review"
    assert {issue["type"] for issue in audit["structural_issues"]} == {
        "missing_fixture_requirements",
        "missing_observation_requirements",
    }


def test_reviewed_empty_and_page_size_points_have_executable_assertions():
    points = {
        point["point_id"]: point
        for points in BASELINE_POINTS.values()
        for point in points
    }

    for point_id in (
        "SHOP-004-NEGATIVE-TYPE-EMPTY",
        "SHOP-004-BOUNDARY-PAGE-EMPTY",
        "SHOP-TYPE-001-CONTRACT-EMPTY",
        "BLOG-008-CONTRACT-EMPTY",
    ):
        assert {
            (assertion["type"], assertion.get("path"), assertion.get("expected"))
            for assertion in points[point_id]["required_assertions"]
        }.__contains__(("json_value", "$.data.length", 0))

    assert (
        "json_value",
        "$.data.length",
        "<=",
        5,
    ) in {
        (a["type"], a.get("path"), a.get("operator"), a.get("expected"))
        for a in points["SHOP-004-POSITIVE"]["required_assertions"]
    }
    assert (
        "json_value",
        "$.data.length",
        "<=",
        10,
    ) in {
        (a["type"], a.get("path"), a.get("operator"), a.get("expected"))
        for a in points["BLOG-008-POSITIVE"]["required_assertions"]
    }
