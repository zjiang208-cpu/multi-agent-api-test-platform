from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from evals.models import AssertionSpec, EvalDatasetManifest, GroundTruthPoint


# 这些点代表独立 HTTP 场景，需要同时约束 HTTP 状态和业务成功标志。
SCENARIO_EXPECTATIONS: dict[str, bool] = {
    "SHOP-001-POSITIVE": True,
    "SHOP-001-BOUNDARY-ID": False,
    "SHOP-001-BOUNDARY-MIN": True,
    "SHOP-001-NEGATIVE-NOT-FOUND": False,
    "SHOP-004-POSITIVE": True,
    "SHOP-004-BOUNDARY-TYPE-ID": False,
    "SHOP-004-BOUNDARY-CURRENT": False,
    "SHOP-004-NEGATIVE-TYPE-EMPTY": True,
    "SHOP-004-BOUNDARY-PAGE-EMPTY": True,
    "SHOP-TYPE-001-POSITIVE": True,
    "SHOP-TYPE-001-CONTRACT-EMPTY": True,
    "VOUCHER-002-POSITIVE": True,
    "VOUCHER-002-BOUNDARY-ID": False,
    "VOUCHER-002-NEGATIVE-NOT-FOUND": False,
    "BLOG-008-POSITIVE": True,
    "BLOG-008-BOUNDARY-CURRENT": False,
    "BLOG-008-CONTRACT-EMPTY": True,
    "USER-004-POSITIVE": True,
    "BLOG-003-POSITIVE": True,
    "BLOG-003-BOUNDARY-ID": False,
    "BLOG-003-NEGATIVE-NOT-FOUND": False,
    "SHOP-TYPE-002-POSITIVE": True,
    "SHOP-TYPE-002-BOUNDARY-NAME": False,
    "SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED": False,
    "SHOP-TYPE-002-BOUNDARY-ICON": False,
    "SHOP-TYPE-002-BOUNDARY-SORT": False,
    "SHOP-TYPE-002-NEGATIVE-DUPLICATE": False,
    "SHOP-TYPE-002-NEGATIVE-SAVE": False,
    "USER-008-POSITIVE": True,
    "USER-008-BOUNDARY-REQUIRED": False,
    "USER-008-BOUNDARY-LENGTH-CITY": False,
    "USER-008-BOUNDARY-LENGTH-INTRODUCE": False,
    "USER-008-NEGATIVE-SAVE": False,
    "SHOP-TYPE-004-POSITIVE": True,
    "SHOP-TYPE-004-BOUNDARY-ID": False,
    "SHOP-TYPE-004-NEGATIVE-NOT-FOUND": False,
    "SHOP-TYPE-004-NEGATIVE-REFERENCED": False,
    "SHOP-TYPE-004-NEGATIVE-DELETE-FAILURE": False,
}


def _manual_observation_point(
    point_id: str,
    description: str,
    observation: str,
    *,
    auth_required: bool = False,
) -> dict[str, Any]:
    fixtures: list[dict[str, Any]] = [
        {
            "reference": f"manual:{point_id}",
            "kind": "observation",
            "description": observation,
            "resolution": "manual_observation",
        }
    ]
    if auth_required:
        fixtures.append(
            {
                "reference": "auth:valid-provider",
                "kind": "auth",
                "description": "使用项目配置的 Auth Provider 注入有效凭据，以隔离参数绑定行为。",
                "resolution": "manual_setup",
            }
        )
    return {
        "point_id": point_id,
        "description": description,
        "category": "negative",
        "required_assertions": [],
        "verification_mode": "observation",
        "observation_requirements": [observation],
        "preconditions": [observation],
        "fixture_requirements": fixtures,
    }


def _invalid_body_point(point_id: str, description: str, precondition: str) -> dict[str, Any]:
    return {
        "point_id": point_id,
        "description": description,
        "category": "negative",
        "required_assertions": [
            {
                "assertion_id": f"{point_id}-STATUS",
                "type": "status_code",
                "operator": "eq",
                "expected": 400,
            },
            {
                "assertion_id": f"{point_id}-SUCCESS",
                "type": "json_value",
                "path": "$.success",
                "expected": False,
            },
            {
                "assertion_id": f"{point_id}-ERROR",
                "type": "json_value",
                "path": "$.errorMsg",
                "expected": "Request body is invalid",
            },
        ],
        "verification_mode": "response_assertion",
        "observation_requirements": [],
        "preconditions": [precondition],
        "fixture_requirements": [
            {
                "reference": "auth:valid-provider",
                "kind": "auth",
                "description": "使用项目配置的 Auth Provider 注入有效凭据。",
                "resolution": "manual_setup",
            }
        ],
    }


ADDED_POINTS: dict[str, list[dict[str, Any]]] = {
    "get-shop-of-type": [
        _manual_observation_point(
            "SHOP-004-NEGATIVE-TYPE-ID-MISSING",
            "缺少必填 typeId 时应在进入业务查询前被请求参数绑定层拒绝。",
            "不传 typeId，确认请求失败且不返回成功业务结果。",
        ),
        _manual_observation_point(
            "SHOP-004-NEGATIVE-TYPE-ID-MISMATCH",
            "typeId 为非数字字面量时应被参数类型转换层拒绝。",
            "传入 typeId=abc，记录实际 HTTP 状态与响应体，不预设业务错误文案。",
        ),
        _manual_observation_point(
            "SHOP-004-NEGATIVE-CURRENT-MISMATCH",
            "current 为非数字字面量时应被参数类型转换层拒绝。",
            "传入 current=abc，记录实际 HTTP 状态与响应体，不预设业务错误文案。",
        ),
    ],
    "get-voucher-id": [
        _manual_observation_point(
            "VOUCHER-002-NEGATIVE-TYPE-MISMATCH",
            "优惠券 ID 为非数字字面量时应被路径参数类型转换层拒绝。",
            "使用有效 Token 请求 /voucher/abc，记录实际 HTTP 状态与响应体。",
            auth_required=True,
        )
    ],
    "get-blog-hot": [
        _manual_observation_point(
            "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
            "current 为非数字字面量时应被参数类型转换层拒绝。",
            "传入 current=abc，记录实际 HTTP 状态与响应体，不预设业务错误文案。",
        )
    ],
    "get-blog-id": [
        _manual_observation_point(
            "BLOG-003-NEGATIVE-TYPE-MISMATCH",
            "笔记 ID 为非数字字面量时应被路径参数类型转换层拒绝。",
            "使用有效 Token 请求 /blog/abc，记录实际 HTTP 状态与响应体。",
            auth_required=True,
        )
    ],
    "post-shop-type": [
        _invalid_body_point(
            "SHOP-TYPE-002-NEGATIVE-INVALID-BODY",
            "缺失、损坏或类型不兼容的 JSON 请求体返回 HTTP 400。",
            "携带有效 Token，提交缺失、损坏或 sort 类型不兼容的 JSON 请求体。",
        )
    ],
    "put-user-info": [
        _invalid_body_point(
            "USER-008-NEGATIVE-INVALID-BODY",
            "缺失或损坏的 JSON 请求体返回 HTTP 400。",
            "携带有效 Token，提交缺失或无法解析的 JSON 请求体。",
        ),
        _invalid_body_point(
            "USER-008-NEGATIVE-BIRTHDAY-FORMAT",
            "birthday 不符合 yyyy-MM-dd 时返回 HTTP 400。",
            "携带有效 Token，提交无法转换为 LocalDate 的 birthday。",
        ),
    ],
    "delete-shop-type-id": [
        _manual_observation_point(
            "SHOP-TYPE-004-NEGATIVE-TYPE-MISMATCH",
            "商铺类型 ID 为非数字字面量时应被路径参数类型转换层拒绝。",
            "携带有效 Token 请求 /shop-type/abc，记录实际 HTTP 状态与响应体。",
            auth_required=True,
        )
    ],
}


def _has_assertion(point: GroundTruthPoint, assertion_type: str, path: str | None) -> bool:
    return any(
        assertion.type == assertion_type and assertion.path == path
        for assertion in point.required_assertions
    )


def _strengthen_scenario(point: GroundTruthPoint, success: bool) -> int:
    additions: list[AssertionSpec] = []
    if not _has_assertion(point, "status_code", None):
        additions.append(
            AssertionSpec(
                assertion_id=f"{point.point_id}-STATUS",
                type="status_code",
                operator="eq",
                expected=200,
            )
        )
    if not _has_assertion(point, "json_value", "$.success"):
        additions.append(
            AssertionSpec(
                assertion_id=f"{point.point_id}-SUCCESS",
                type="json_value",
                path="$.success",
                expected=success,
            )
        )
    point.required_assertions = additions + point.required_assertions
    return len(additions)


def review_manifest(manifest: EvalDatasetManifest) -> tuple[EvalDatasetManifest, dict[str, Any]]:
    expected_operations = {
        "get-shop-id",
        "get-shop-of-type",
        "get-shop-type-list",
        "get-voucher-id",
        "get-blog-hot",
        "get-user-me",
        "get-blog-id",
        "post-shop-type",
        "put-user-info",
        "delete-shop-type-id",
    }
    actual_operations = {operation.operation_id for operation in manifest.operations}
    if actual_operations != expected_operations:
        raise ValueError("baseline operation set changed; review decisions must be revisited")

    strengthened_assertions = 0
    added_point_ids: list[str] = []
    for operation in manifest.operations:
        existing_ids = {point.point_id for point in operation.points}
        for raw_point in ADDED_POINTS.get(operation.operation_id, []):
            if raw_point["point_id"] not in existing_ids:
                operation.points.append(GroundTruthPoint.model_validate(raw_point))
                added_point_ids.append(raw_point["point_id"])
        for point in operation.points:
            expected_success = SCENARIO_EXPECTATIONS.get(point.point_id)
            if expected_success is not None:
                strengthened_assertions += _strengthen_scenario(point, expected_success)
            if point.point_id == "USER-008-BOUNDARY-REQUIRED":
                point.description = "请求体为 JSON null 时返回业务失败 user info is required。"
                point.preconditions = ["携带有效 Token，并提交 JSON null 请求体。"]
        operation.annotation_status = "verified"
        operation.reviewed_at = date.today().isoformat()
        operation.review_basis = [
            "requirement_document",
            "controller_and_service_source",
            "auth_and_exception_pipeline",
            "database_and_cache_contract",
        ]

    all_point_ids = [point.point_id for operation in manifest.operations for point in operation.points]
    if len(all_point_ids) != len(set(all_point_ids)):
        raise ValueError("duplicate Ground Truth point IDs")
    assertion_ids = [
        assertion.assertion_id
        for operation in manifest.operations
        for point in operation.points
        for assertion in point.required_assertions
    ]
    if len(assertion_ids) != len(set(assertion_ids)):
        raise ValueError("duplicate Ground Truth assertion IDs")

    manifest.annotation_status = "verified"
    manifest.version = "1.1.0"
    manifest.notes = (
        "Verified against local requirement documents and the current hm-dianping source snapshot. "
        "Response assertions and observation-only contracts are scored separately."
    )
    record = {
        "review_id": "baseline-v1-ground-truth-review-20260820",
        "status": "verified",
        "reviewed_at": date.today().isoformat(),
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.version,
        "operation_count": len(manifest.operations),
        "point_count": len(all_point_ids),
        "required_assertion_count": len(assertion_ids),
        "strengthened_assertion_count": strengthened_assertions,
        "added_point_ids": added_point_ids,
        "evidence": [
            "docs/api 下对应接口需求文档",
            "Controller 与 Service 当前实现",
            "LoginInterceptor、RefreshTokenInterceptor 与 WebExceptionAdvice",
            "实体、Mapper SQL 与数据库约束",
        ],
        "decisions": [
            "独立 HTTP 场景要求状态码、success 与场景特有断言同时闭合",
            "缓存、数据库副作用和多状态比对保留为 observation",
            "数值参数非数字输入纳入 Ground Truth；响应不稳定时不预设状态与正文",
            "JSON null 业务失败与缺失或损坏请求体的 HTTP 400 分开建模",
        ],
        "open_questions": [],
    }
    return EvalDatasetManifest.model_validate(manifest.model_dump(mode="json")), record


def main() -> int:
    parser = argparse.ArgumentParser(description="按人工证据审阅决定校订 baseline_v1 Ground Truth")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()

    payload = yaml.safe_load(args.input.read_text(encoding="utf-8")) or {}
    reviewed, record = review_manifest(EvalDatasetManifest.model_validate(payload))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(reviewed.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    args.record.write_text(
        yaml.safe_dump(record, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(
        yaml.safe_dump(
            {
                "status": reviewed.annotation_status,
                "operations": len(reviewed.operations),
                "points": record["point_count"],
                "required_assertions": record["required_assertion_count"],
                "added_points": len(record["added_point_ids"]),
                "strengthened_assertions": record["strengthened_assertion_count"],
            },
            allow_unicode=True,
            sort_keys=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
