from __future__ import annotations

from collections import Counter
from typing import Any

from evals.models import EvalDatasetManifest


def audit_fixture_requirements(manifest: EvalDatasetManifest) -> dict[str, Any]:
    """只读审计 Ground Truth 的脱敏 Fixture 计划。

    该审计只检查清单结构和引用分配，不解析令牌、不访问数据库、缓存、
    Redis、鉴权服务或被测系统。``ready`` 仅表示计划结构完整，不表示
    测试环境已经准备好。
    """

    resolution_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    local_tokens: list[dict[str, str]] = []
    manual_items: list[dict[str, str]] = []
    structural_issues: list[dict[str, str]] = []
    point_count = 0
    precondition_point_count = 0
    observation_point_count = 0

    for operation in manifest.operations:
        for point in operation.points:
            point_count += 1
            if point.preconditions:
                precondition_point_count += 1
                if not point.fixture_requirements:
                    structural_issues.append(
                        {
                            "type": "missing_fixture_requirements",
                            "operation_id": operation.operation_id,
                            "point_id": point.point_id,
                            "message": "存在中文前置条件，但没有对应的 Fixture 计划。",
                        }
                    )
            if point.verification_mode == "observation":
                observation_point_count += 1
                if not point.observation_requirements:
                    structural_issues.append(
                        {
                            "type": "missing_observation_requirements",
                            "operation_id": operation.operation_id,
                            "point_id": point.point_id,
                            "message": "观察点没有声明 observation_requirements。",
                        }
                    )

            references: set[str] = set()
            for requirement in point.fixture_requirements:
                resolution_counts[requirement.resolution] += 1
                kind_counts[requirement.kind] += 1
                if requirement.reference in references:
                    structural_issues.append(
                        {
                            "type": "duplicate_fixture_reference",
                            "operation_id": operation.operation_id,
                            "point_id": point.point_id,
                            "reference": requirement.reference,
                            "message": "同一个评测点重复声明了 Fixture reference。",
                        }
                    )
                references.add(requirement.reference)

                base = {
                    "operation_id": operation.operation_id,
                    "point_id": point.point_id,
                    "reference": requirement.reference,
                    "kind": requirement.kind,
                    "resolution": requirement.resolution,
                    "description": requirement.description,
                }
                if requirement.resolution == "local_token":
                    if not requirement.token:
                        structural_issues.append(
                            {
                                "type": "missing_local_token",
                                "operation_id": operation.operation_id,
                                "point_id": point.point_id,
                                "reference": requirement.reference,
                                "message": "local_token 计划缺少安全令牌。",
                            }
                        )
                    else:
                        local_tokens.append({**base, "token": requirement.token})
                else:
                    manual_items.append(base)

    return {
        "status": "ready" if not structural_issues else "needs_review",
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.version,
        "annotation_status": manifest.annotation_status,
        "operations": len(manifest.operations),
        "points": point_count,
        "precondition_points": precondition_point_count,
        "observation_points": observation_point_count,
        "fixture_requirements": sum(resolution_counts.values()),
        "by_resolution": dict(sorted(resolution_counts.items())),
        "by_kind": dict(sorted(kind_counts.items())),
        "local_tokens": local_tokens,
        "manual_items": manual_items,
        "structural_issues": structural_issues,
        "notes": [
            "ready 只表示 Fixture 计划结构完整，不表示本地数据库、缓存或服务状态已准备好。",
            "本报告不包含真实 ID、名称、凭据、Cookie、DSN 或模型原始输出。",
        ],
    }
