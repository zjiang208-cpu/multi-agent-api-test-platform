from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evals.models import AssertionMatch, EvalAnnotations, EvalSample, PointMatch


# 这些映射来自逐接口人工复核；没有明确语义对应的点不写入映射。
POINT_MAPPINGS: dict[str, dict[str, str]] = {
    "get-shop-id": {
        "tp-get-shop-id-2d82e44a-001": "SHOP-001-POSITIVE",
        "tp-get-shop-id-2d82e44a-002": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-003": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-004": "SHOP-001-NEGATIVE-NOT-FOUND",
        "tp-get-shop-id-2d82e44a-005": "SHOP-001-NEGATIVE-TYPE-MISMATCH",
    },
    "get-shop-id-2d82e44a": {
        "tp-get-shop-id-2d82e44a-001": "SHOP-001-POSITIVE",
        "tp-get-shop-id-2d82e44a-002": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-003": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-004": "SHOP-001-NEGATIVE-NOT-FOUND",
        "tp-get-shop-id-2d82e44a-005": "SHOP-001-NEGATIVE-TYPE-MISMATCH",
    },
    "get-shop-of-type": {
        "tp-get-shop-of-type-001": "SHOP-004-POSITIVE",
        "tp-get-shop-of-type-002": "SHOP-004-POSITIVE",
        "tp-get-shop-of-type-003": "SHOP-004-POSITIVE",
        "tp-get-shop-of-type-004": "SHOP-004-BOUNDARY-TYPE-ID",
        "tp-get-shop-of-type-005": "SHOP-004-BOUNDARY-CURRENT",
        "tp-get-shop-of-type-006": "SHOP-004-NEGATIVE-TYPE-ID-MISMATCH",
        "tp-get-shop-of-type-007": "SHOP-004-NEGATIVE-CURRENT-MISMATCH",
        "TP-get-shop-of-type-001": "SHOP-004-POSITIVE",
        "TP-get-shop-of-type-002": "SHOP-004-POSITIVE",
        "TP-get-shop-of-type-003": "SHOP-004-POSITIVE",
        "TP-get-shop-of-type-004": "SHOP-004-CONTRACT-METADATA",
        "TP-get-shop-of-type-005": "SHOP-004-BOUNDARY-TYPE-ID",
        "TP-get-shop-of-type-006": "SHOP-004-BOUNDARY-CURRENT",
        "TP-get-shop-of-type-007": "SHOP-004-NEGATIVE-TYPE-ID-MISSING",
        "TP-get-shop-of-type-008": "SHOP-004-NEGATIVE-TYPE-ID-MISMATCH",
        "TP-get-shop-of-type-009": "SHOP-004-NEGATIVE-CURRENT-MISMATCH",
    },
    "get-shop-type-list": {
        "tp-get-shop-type-list-001": "SHOP-TYPE-001-POSITIVE",
        "tp-get-shop-type-list-002": "SHOP-TYPE-001-CONTRACT-SORT",
        "tp-get-shop-type-list-003": "SHOP-TYPE-001-CONTRACT-EMPTY",
        "tp-get-shop-type-list-004": "SHOP-TYPE-001-CONTRACT-FIELDS",
    },
    "get-voucher-id": {
        "TP-VOUCHER-002-001": "VOUCHER-002-POSITIVE",
        "TP-VOUCHER-002-002": "VOUCHER-002-CONTRACT-NORMAL-FIELDS",
        "TP-VOUCHER-002-003": "VOUCHER-002-CONTRACT-SECKILL-FIELDS",
        "TP-VOUCHER-002-004": "VOUCHER-002-CONTRACT-STATUS",
        "TP-VOUCHER-002-005": "VOUCHER-002-BOUNDARY-ID",
        "TP-VOUCHER-002-006": "VOUCHER-002-BOUNDARY-ID",
        "TP-VOUCHER-002-007": "VOUCHER-002-NEGATIVE-TYPE-MISMATCH",
        "TP-VOUCHER-002-008": "VOUCHER-002-NEGATIVE-NOT-FOUND",
    },
    "get-blog-hot": {
        "tp-get-blog-hot-001": "BLOG-008-CONTRACT-SORT",
        "tp-get-blog-hot-002": "BLOG-008-BOUNDARY-CURRENT",
        "tp-get-blog-hot-003": "BLOG-008-BOUNDARY-CURRENT",
        "tp-get-blog-hot-004": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "tp-get-blog-hot-005": "BLOG-008-CONTRACT-EMPTY",
        "tp-get-blog-hot-006": "BLOG-008-CONTRACT-ANONYMOUS-LIKE",
        "tp-get-blog-hot-007": "BLOG-008-CONTRACT-NO-TOTAL",
        "tp-get-blog-hot-008": "BLOG-008-POSITIVE",
    },
    "get-user-me": {
        "tp-get-user-me-001": "USER-004-POSITIVE",
        "tp-get-user-me-002": "USER-004-AUTH",
        "tp-get-user-me-003": "USER-004-AUTH",
        "tp-get-user-me-004": "USER-004-CONTRACT-SENSITIVE",
    },
    "get-blog-id": {
        "tp-get-blog-id-001": "BLOG-003-POSITIVE",
        "tp-get-blog-id-002": "BLOG-003-BOUNDARY-ID",
        "tp-get-blog-id-003": "BLOG-003-NEGATIVE-NOT-FOUND",
        "tp-get-blog-id-004": "BLOG-003-NEGATIVE-TYPE-MISMATCH",
        "tp-get-blog-id-005": "BLOG-003-CONTRACT-AUTHENTICATED-LIKE",
        "tp-get-blog-id-006": "BLOG-003-CONTRACT-AUTHENTICATED-LIKE",
    },
    "post-shop-type": {
        "TP-SHOP-TYPE-002-001": "SHOP-TYPE-002-POSITIVE",
        "TP-SHOP-TYPE-002-002": "SHOP-TYPE-002-BOUNDARY-NAME",
        "TP-SHOP-TYPE-002-003": "SHOP-TYPE-002-BOUNDARY-ICON",
        "TP-SHOP-TYPE-002-004": "SHOP-TYPE-002-CONTRACT-SORT-DEFAULT",
        "TP-SHOP-TYPE-002-005": "SHOP-TYPE-002-BOUNDARY-SORT",
        "TP-SHOP-TYPE-002-006": "SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED",
        "TP-SHOP-TYPE-002-007": "SHOP-TYPE-002-BOUNDARY-NAME",
        "TP-SHOP-TYPE-002-008": "SHOP-TYPE-002-BOUNDARY-ICON",
        "TP-SHOP-TYPE-002-009": "SHOP-TYPE-002-BOUNDARY-SORT",
        "TP-SHOP-TYPE-002-010": "SHOP-TYPE-002-AUTH",
        "TP-SHOP-TYPE-002-011": "SHOP-TYPE-002-AUTH",
        "req-post-shop-type-tp-01": "SHOP-TYPE-002-POSITIVE",
        "req-post-shop-type-tp-03": "SHOP-TYPE-002-BOUNDARY-ICON",
        "req-post-shop-type-tp-04": "SHOP-TYPE-002-BOUNDARY-NAME",
        "req-post-shop-type-tp-05": "SHOP-TYPE-002-BOUNDARY-NAME",
        "req-post-shop-type-tp-06": "SHOP-TYPE-002-BOUNDARY-ICON",
        "req-post-shop-type-tp-07": "SHOP-TYPE-002-BOUNDARY-SORT",
        "req-post-shop-type-tp-08": "SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED",
        "req-post-shop-type-tp-09": "SHOP-TYPE-002-AUTH",
        "req-post-shop-type-tp-10": "SHOP-TYPE-002-AUTH",
        "tp-post-shop-type-001": "SHOP-TYPE-002-POSITIVE",
        "tp-post-shop-type-003": "SHOP-TYPE-002-CONTRACT-SORT-DEFAULT",
        "tp-post-shop-type-004": "SHOP-TYPE-002-BOUNDARY-SORT",
        "tp-post-shop-type-005": "SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED",
        "tp-post-shop-type-006": "SHOP-TYPE-002-BOUNDARY-NAME",
        "tp-post-shop-type-007": "SHOP-TYPE-002-BOUNDARY-NAME",
        "tp-post-shop-type-008": "SHOP-TYPE-002-BOUNDARY-ICON",
        "tp-post-shop-type-009": "SHOP-TYPE-002-BOUNDARY-ICON",
        "tp-post-shop-type-010": "SHOP-TYPE-002-NEGATIVE-DUPLICATE",
        "tp-post-shop-type-011": "SHOP-TYPE-002-AUTH",
        "tp-post-shop-type-012": "SHOP-TYPE-002-AUTH",
    },
    "put-user-info": {
        "TP-USER-008-01": "USER-008-POSITIVE",
        "TP-USER-008-02": "USER-008-POSITIVE",
        "TP-USER-008-03": "USER-008-BOUNDARY-LENGTH-CITY",
        "TP-USER-008-04": "USER-008-BOUNDARY-LENGTH-CITY",
        "TP-USER-008-05": "USER-008-BOUNDARY-LENGTH-INTRODUCE",
        "TP-USER-008-06": "USER-008-BOUNDARY-LENGTH-INTRODUCE",
        "TP-USER-008-07": "USER-008-BOUNDARY-REQUIRED",
        "TP-USER-008-08": "USER-008-NEGATIVE-INVALID-BODY",
        "TP-USER-008-09": "USER-008-AUTH",
        "TP-USER-008-10": "USER-008-AUTH",
    },
    "delete-shop-type-id": {
        "TP-SHOP-TYPE-004-001": "SHOP-TYPE-004-POSITIVE",
        "TP-SHOP-TYPE-004-002": "SHOP-TYPE-004-AUTH",
        "TP-SHOP-TYPE-004-003": "SHOP-TYPE-004-AUTH",
        "TP-SHOP-TYPE-004-004": "SHOP-TYPE-004-BOUNDARY-ID",
        "TP-SHOP-TYPE-004-005": "SHOP-TYPE-004-NEGATIVE-NOT-FOUND",
        "TP-SHOP-TYPE-004-006": "SHOP-TYPE-004-NEGATIVE-REFERENCED",
        "TP-SHOP-TYPE-004-007": "SHOP-TYPE-004-NEGATIVE-DELETE-FAILURE",
    },
}

# 当前提示词版本的点编号发生过语义重排；这里按本次样本中人工确认的
# 语义关系单独维护，避免用 001/002/003 的序号冒充稳定语义。
SEMANTIC_POINT_MAPPINGS: dict[str, dict[str, str]] = {
    "get-shop-type-list": {
        "tp-get-shop-type-list-001": "SHOP-TYPE-001-POSITIVE",
        "tp-get-shop-type-list-002": "SHOP-TYPE-001-CONTRACT-EMPTY",
        "tp-get-shop-type-list-003": "SHOP-TYPE-001-CONTRACT-SORT",
        "tp-get-shop-type-list-004": "SHOP-TYPE-001-CONTRACT-FIELDS",
        "TP-get-shop-type-list-001": "SHOP-TYPE-001-POSITIVE",
        "TP-get-shop-type-list-002": "SHOP-TYPE-001-CONTRACT-EMPTY",
        "TP-get-shop-type-list-003": "SHOP-TYPE-001-CONTRACT-SORT",
        "TP-get-shop-type-list-004": "SHOP-TYPE-001-CONTRACT-FIELDS",
    },
    "get-blog-hot": {
        "TP-get-blog-hot-001": "BLOG-008-CONTRACT-ANONYMOUS-LIKE",
        "TP-get-blog-hot-002": "BLOG-008-POSITIVE",
        "TP-get-blog-hot-003": "BLOG-008-CONTRACT-SORT",
        "TP-get-blog-hot-004": "BLOG-008-POSITIVE",
        "TP-get-blog-hot-005": "BLOG-008-CONTRACT-NO-TOTAL",
        "TP-get-blog-hot-006": "BLOG-008-BOUNDARY-CURRENT",
        "TP-get-blog-hot-007": "BLOG-008-CONTRACT-EMPTY",
        "TP-get-blog-hot-008": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "TP-get-blog-hot-009": "BLOG-008-CONTRACT-AUTHENTICATED-LIKE",
        "TP-BLOG-HOT-001": "BLOG-008-POSITIVE",
        "TP-BLOG-HOT-002": "BLOG-008-BOUNDARY-CURRENT",
        "TP-BLOG-HOT-003": "BLOG-008-BOUNDARY-CURRENT",
        "TP-BLOG-HOT-004": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "TP-BLOG-HOT-005": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "TP-BLOG-HOT-006": "BLOG-008-CONTRACT-ANONYMOUS-LIKE",
        "TP-BLOG-HOT-007": "BLOG-008-CONTRACT-AUTHENTICATED-LIKE",
        "TP-BLOG-HOT-008": "BLOG-008-CONTRACT-NO-TOTAL",
        "TP-BLOG-HOT-009": "BLOG-008-CONTRACT-SORT",
        "tp-get-blog-hot-001": "BLOG-008-POSITIVE",
        "tp-get-blog-hot-002": "BLOG-008-BOUNDARY-CURRENT",
        "tp-get-blog-hot-003": "BLOG-008-BOUNDARY-CURRENT",
        "tp-get-blog-hot-004": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "tp-get-blog-hot-005": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "tp-get-blog-hot-006": "BLOG-008-CONTRACT-ANONYMOUS-LIKE",
        "tp-get-blog-hot-007": "BLOG-008-CONTRACT-AUTHENTICATED-LIKE",
        "tp-get-blog-hot-008": "BLOG-008-CONTRACT-NO-TOTAL",
        "tp-get-blog-hot-009": "BLOG-008-CONTRACT-SORT",
    },
}

# 当前提示词版本的完整人工语义映射。旧 POINT_MAPPINGS 继续服务历史样本，
# 本表只用于本轮重新生成的 1.6.0 样本，避免编号重排造成假性漏测。
CURRENT_POINT_MAPPINGS: dict[str, dict[str, str]] = {
    "get-shop-id": {
        "tp-get-shop-id-2d82e44a-001": "SHOP-001-POSITIVE",
        "tp-get-shop-id-2d82e44a-002": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-003": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-004": "SHOP-001-NEGATIVE-NOT-FOUND",
        "tp-get-shop-id-2d82e44a-005": "SHOP-001-NEGATIVE-TYPE-MISMATCH",
    },
    "get-shop-id-2d82e44a": {
        "tp-get-shop-id-2d82e44a-001": "SHOP-001-POSITIVE",
        "tp-get-shop-id-2d82e44a-002": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-003": "SHOP-001-BOUNDARY-ID",
        "tp-get-shop-id-2d82e44a-004": "SHOP-001-NEGATIVE-NOT-FOUND",
        "tp-get-shop-id-2d82e44a-005": "SHOP-001-NEGATIVE-TYPE-MISMATCH",
    },
    "get-shop-of-type": {
        "tp-get-shop-of-type-001": "SHOP-004-POSITIVE",
        "tp-get-shop-of-type-002": "SHOP-004-POSITIVE",
        "tp-get-shop-of-type-003": "SHOP-004-NEGATIVE-TYPE-ID-MISSING",
        "tp-get-shop-of-type-004": "SHOP-004-BOUNDARY-TYPE-ID",
        "tp-get-shop-of-type-005": "SHOP-004-BOUNDARY-TYPE-ID",
        "tp-get-shop-of-type-006": "SHOP-004-NEGATIVE-TYPE-ID-MISMATCH",
        "tp-get-shop-of-type-007": "SHOP-004-BOUNDARY-CURRENT",
        "tp-get-shop-of-type-008": "SHOP-004-NEGATIVE-CURRENT-MISMATCH",
        "TP-AUTO-7458C51CDE03": "SHOP-004-BOUNDARY-CURRENT",
    },
    "get-shop-type-list": {
        "TP-get-shop-type-list-001": "SHOP-TYPE-001-POSITIVE",
        "TP-get-shop-type-list-002": "SHOP-TYPE-001-CONTRACT-EMPTY",
        "TP-get-shop-type-list-003": "SHOP-TYPE-001-CONTRACT-SORT",
        "TP-get-shop-type-list-004": "SHOP-TYPE-001-CONTRACT-FIELDS",
    },
    "get-voucher-id": {
        "TP-get-voucher-id-001": "VOUCHER-002-POSITIVE",
        "TP-get-voucher-id-002": "VOUCHER-002-CONTRACT-NORMAL-FIELDS",
        "TP-get-voucher-id-003": "VOUCHER-002-CONTRACT-SECKILL-FIELDS",
        "TP-get-voucher-id-004": "VOUCHER-002-NEGATIVE-NOT-FOUND",
        "TP-get-voucher-id-005": "VOUCHER-002-BOUNDARY-ID",
        "TP-get-voucher-id-006": "VOUCHER-002-BOUNDARY-ID",
        "TP-get-voucher-id-007": "VOUCHER-002-NEGATIVE-TYPE-MISMATCH",
    },
    "get-blog-hot": {
        "TP-get-blog-hot-001": "BLOG-008-CONTRACT-ANONYMOUS-LIKE",
        "TP-get-blog-hot-002": "BLOG-008-POSITIVE",
        "TP-get-blog-hot-003": "BLOG-008-CONTRACT-SORT",
        "TP-get-blog-hot-004": "BLOG-008-POSITIVE",
        "TP-get-blog-hot-005": "BLOG-008-CONTRACT-NO-TOTAL",
        "TP-get-blog-hot-006": "BLOG-008-BOUNDARY-CURRENT",
        "TP-get-blog-hot-007": "BLOG-008-CONTRACT-EMPTY",
        "TP-get-blog-hot-008": "BLOG-008-NEGATIVE-CURRENT-MISMATCH",
        "TP-get-blog-hot-009": "BLOG-008-CONTRACT-AUTHENTICATED-LIKE",
        # 兼容早期同一轮快照使用的大写 ID 别名。
        "TP-BLOG-HOT-001": "BLOG-008-POSITIVE",
        "TP-BLOG-HOT-008": "BLOG-008-CONTRACT-NO-TOTAL",
        "TP-BLOG-HOT-009": "BLOG-008-CONTRACT-SORT",
    },
    "get-user-me": {
        "REQ-get-user-me-001-TP001": "USER-004-POSITIVE",
        "REQ-get-user-me-001-TP002": "USER-004-AUTH",
        "REQ-get-user-me-001-TP003": "USER-004-AUTH",
        "REQ-get-user-me-001-TP004": "USER-004-CONTRACT-SENSITIVE",
        "REQ-get-user-me-001-TP005": "USER-004-CONTRACT-SENSITIVE",
    },
    "get-blog-id": {
        "TP-GET-BLOG-ID-001": "BLOG-003-CONTRACT-ANONYMOUS-LIKE",
        "TP-GET-BLOG-ID-002": "BLOG-003-NEGATIVE-NOT-FOUND",
        "TP-GET-BLOG-ID-003": "BLOG-003-BOUNDARY-ID",
        "TP-GET-BLOG-ID-004": "BLOG-003-BOUNDARY-ID",
        "TP-GET-BLOG-ID-005": "BLOG-003-NEGATIVE-TYPE-MISMATCH",
    },
    "post-shop-type": {
        "TP-001": "SHOP-TYPE-002-POSITIVE",
        "TP-002": "SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED",
        "TP-003": "SHOP-TYPE-002-POSITIVE",
        "TP-004": "SHOP-TYPE-002-BOUNDARY-NAME",
        "TP-005": "SHOP-TYPE-002-POSITIVE",
        "TP-006": "SHOP-TYPE-002-BOUNDARY-ICON",
        "TP-007": "SHOP-TYPE-002-CONTRACT-SORT-DEFAULT",
        "TP-008": "SHOP-TYPE-002-POSITIVE",
        "TP-009": "SHOP-TYPE-002-BOUNDARY-SORT",
        "TP-010": "SHOP-TYPE-002-NEGATIVE-DUPLICATE",
        "TP-011": "SHOP-TYPE-002-AUTH",
        "TP-012": "SHOP-TYPE-002-AUTH",
    },
    "put-user-info": {
        "tp-put-user-info-001": "USER-008-POSITIVE",
        "tp-put-user-info-002": "USER-008-POSITIVE",
        "tp-put-user-info-003": "USER-008-POSITIVE",
        "tp-put-user-info-004": "USER-008-BOUNDARY-LENGTH-CITY",
        "tp-put-user-info-005": "USER-008-POSITIVE",
        "tp-put-user-info-006": "USER-008-BOUNDARY-LENGTH-INTRODUCE",
        "tp-put-user-info-007": "USER-008-BOUNDARY-REQUIRED",
        "tp-put-user-info-008": "USER-008-NEGATIVE-INVALID-BODY",
        "tp-put-user-info-009": "USER-008-AUTH",
        "tp-put-user-info-010": "USER-008-AUTH",
    },
    "delete-shop-type-id": {
        "tp-delete-shop-type-001": "SHOP-TYPE-004-POSITIVE",
        "tp-delete-shop-type-002": "SHOP-TYPE-004-NEGATIVE-REFERENCED",
        "tp-delete-shop-type-003": "SHOP-TYPE-004-NEGATIVE-NOT-FOUND",
        "tp-delete-shop-type-004": "SHOP-TYPE-004-BOUNDARY-ID",
        "tp-delete-shop-type-005": "SHOP-TYPE-004-AUTH",
        "tp-delete-shop-type-006": "SHOP-TYPE-004-AUTH",
    },
}


def _mapping_for_sample(sample: EvalSample) -> dict[str, str]:
    """按样本标记选择映射，历史样本继续使用原始人工标注。"""

    profile = sample.metadata.get("point_mapping_profile")
    if profile == "baseline_v1_semantic_v2":
        return SEMANTIC_POINT_MAPPINGS.get(sample.operation_id) or POINT_MAPPINGS[sample.operation_id]
    # 当前实际工作流已使用 Designer 1.5.9/1.6.0；旧脱敏基线仍是 1.5.8。
    if (
        sample.metadata.get("designer_prompt_version") in {"1.5.9", "1.6.0"}
        and sample.operation_id in CURRENT_POINT_MAPPINGS
    ):
        return CURRENT_POINT_MAPPINGS[sample.operation_id]
    return POINT_MAPPINGS[sample.operation_id]


def _same(left: Any, right: Any) -> bool:
    return left == right


def _normalized_operator(assertion_type: str, operator: str | None) -> str | None:
    """将断言中可证明等价的操作符写法归一化后再匹配。"""
    aliases = {
        "==": "eq",
        "<=": "le",
        ">=": "ge",
        "<": "lt",
        ">": "gt",
    }
    if assertion_type in {"status_code", "json_value"} and operator is None:
        return "eq"
    if assertion_type == "json_exists" and operator in {None, "eq"}:
        return "exists"
    return aliases.get(operator, operator)


def _assertion_semantically_matches(required: dict[str, Any], generated: Any) -> bool:
    """只放宽表示形式，不放宽断言类型、路径或期望值。"""
    return (
        required.get("type") == generated.type
        and required.get("path") == generated.path
        and _normalized_operator(required.get("type"), required.get("operator"))
        == _normalized_operator(generated.type, generated.operator)
        and _same(required.get("expected"), generated.expected)
    )


def _ground_truth_index(manifest_path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return {
        operation["operation_id"]: {
            point["point_id"]: point
            for point in operation.get("points", [])
        }
        for operation in manifest.get("operations", [])
    }


def _annotations(
    sample: EvalSample,
    ground_truth: dict[str, dict[str, Any]],
    *,
    review_missing_assertions: bool = False,
) -> EvalAnnotations:
    mapping = _mapping_for_sample(sample)
    generated_ids = {point.point_id for point in sample.test_points}
    point_matches = [
        PointMatch(
            generated_point_id=point.point_id,
            ground_truth_point_id=mapping.get(point.point_id),
            supported=point.point_id in mapping,
            notes=(
                "人工确认语义对应；可执行性和夹具缺口由 Designer/Reviewer 指标另行反映。"
                if point.point_id in mapping
                else "人工确认该点暂无对应 Ground Truth，作为未支持的额外生成点保留。"
            ),
        )
        for point in sample.test_points
    ]
    assertion_matches: list[AssertionMatch] = []
    for case in sample.cases:
        target_points = [
            ground_truth[mapping[point_id]]
            for point_id in case.test_point_ids
            if point_id in mapping and mapping[point_id] in ground_truth
        ]
        candidates = [
            assertion
            for point in target_points
            for assertion in point.get("required_assertions", [])
        ]
        for generated in case.assertions:
            matches = [
                required
                for required in candidates
                if _assertion_semantically_matches(required, generated)
            ]
            for match in matches:
                assertion_matches.append(
                    AssertionMatch(
                        case_id=case.case_id,
                        generated_assertion_id=generated.assertion_id,
                        ground_truth_assertion_id=match["assertion_id"],
                    )
                )
    required_assertion_ids = {
        assertion["assertion_id"]
        for point in ground_truth.values()
        for assertion in point.get("required_assertions", [])
        if assertion.get("required", True)
    }
    matched_assertion_ids = {
        item.ground_truth_assertion_id for item in assertion_matches
    }
    return EvalAnnotations(
        point_matches=point_matches,
        assertion_matches=assertion_matches,
        reviewed_missing_assertion_ids=(
            sorted(required_assertion_ids - matched_assertion_ids)
            if review_missing_assertions
            else []
        ),
    )


def annotate(
    input_dir: Path,
    manifest_path: Path,
    operation_ids: list[str] | None = None,
    *,
    review_missing_assertions: bool = False,
) -> None:
    ground_truth = _ground_truth_index(manifest_path)
    for operation_id in operation_ids or list(POINT_MAPPINGS):
        path = input_dir / f"{operation_id}-current-redacted.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        sample = EvalSample.model_validate(payload["samples"][0])
        sample.annotations = _annotations(
            sample,
            ground_truth[operation_id],
            review_missing_assertions=review_missing_assertions,
        )
        path.write_text(
            json.dumps({"samples": [sample.model_dump(mode="json", exclude_none=True)]}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(
            f"ANNOTATED {operation_id}: points={len(sample.annotations.point_matches)} "
            f"assertions={len(sample.annotations.assertion_matches)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 baseline_v1 新样本的人工 Ground Truth 映射")
    parser.add_argument("--input-dir", type=Path, default=Path("evals/reports/baseline_v1/generated/samples"))
    parser.add_argument("--manifest", type=Path, default=Path("evals/datasets/baseline_v1/manifest.yaml"))
    parser.add_argument("--operation", action="append", choices=list(POINT_MAPPINGS))
    parser.add_argument(
        "--review-missing-assertions",
        action="store_true",
        help="将人工已确认的未生成必要断言显式登记为评测缺口",
    )
    args = parser.parse_args()
    annotate(
        args.input_dir,
        args.manifest,
        args.operation,
        review_missing_assertions=args.review_missing_assertions,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
