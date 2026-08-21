from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

from evals.baseline_ground_truth import BASELINE_INTERFACE_TO_OPERATION, points_for_interface


_INTERFACE_ID = re.compile(r"[A-Z]+(?:-[A-Z0-9]+)+")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
_NORMALIZED_INTERFACE_IDS = {
    "user/delete-current-user.md": "USER-009",
}
_SCOPE_EXCLUSIONS = [
    {
        "domain": "USER",
        "interface_ids": ["USER-001", "USER-002"],
        "reason": "当前 docs/api 未提供登录、验证码等接口需求文档，暂不纳入本评测数据集。",
    }
]


def _clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def _table_rows(lines: list[str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in lines:
        match = _TABLE_ROW.match(line.strip())
        if not match:
            continue
        cells = [_clean_cell(cell) for cell in match.group(1).split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", ":", " "}:
            continue
        rows.append((cells[0], cells[1]))
    return rows


def _first_heading(lines: list[str], level: int) -> str:
    prefix = "#" * level
    for line in lines:
        match = _HEADING.match(line)
        if match and match.group(1) == prefix:
            return match.group(2).strip()
    return ""


def _section_titles(lines: list[str]) -> list[str]:
    return [match.group(2).strip() for line in lines if (match := _HEADING.match(line)) and len(match.group(1)) == 2]


def _basic_info(lines: list[str]) -> dict[str, str]:
    try:
        start = next(index for index, line in enumerate(lines) if re.match(r"^##\s+1\.", line))
    except StopIteration:
        start = 0
    try:
        end = next(index for index in range(start, len(lines)) if re.match(r"^##\s+2\.", lines[index]))
    except StopIteration:
        end = len(lines)
    return dict(_table_rows(lines[start:end]))


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _candidate_points(interface_id: str, text: str, info: dict[str, str], titles: list[str]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = [
        {
            "point_id": f"{interface_id}-POSITIVE",
            "description": "满足文档约束的正常请求应返回成功响应和符合契约的数据。",
            "category": "positive",
            "required_assertions": [],
        }
    ]
    permission = info.get("权限", "")
    if "登录" in permission:
        points.append(
            {
                "point_id": f"{interface_id}-AUTH",
                "description": "受保护接口在缺少、过期或无效 Token 时应拒绝访问。",
                "category": "auth",
                "required_assertions": [],
            }
        )
    if _has_any(text, ("约束", "必填", "最大", "最小", "最长", "大于0", "小于", "为空", "文件头")):
        points.append(
            {
                "point_id": f"{interface_id}-BOUNDARY",
                "description": "参数处于空值、非法值或声明边界时，应按文档约束处理。",
                "category": "boundary",
                "required_assertions": [],
            }
        )
    if "失败场景" in titles or _has_any(text, ("不存在", "非法", "重复", "不足", "失败", "未开始", "已结束")):
        points.append(
            {
                "point_id": f"{interface_id}-NEGATIVE",
                "description": "已知业务失败条件应返回可识别的失败结果，不得伪装成成功。",
                "category": "negative",
                "required_assertions": [],
            }
        )
    if "业务规则" in text or _has_any(text, ("缓存", "Redis", "MySQL", "RabbitMQ", "幂等", "所有权", "敏感", "目录")):
        points.append(
            {
                "point_id": f"{interface_id}-CONTRACT",
                "description": "业务副作用、权限边界、数据一致性和响应字段应符合文档契约。",
                "category": "contract",
                "required_assertions": [],
            }
        )
    return points


def parse_requirement_file(path: Path, source_root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    info = _basic_info(lines)
    raw_id = info.get("接口编号", "")
    interface_id = _INTERFACE_ID.search(raw_id)
    source_interface_id = interface_id.group(0) if interface_id else path.stem.upper()
    method_value = info.get("方法") or ""
    method_match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", method_value.upper())
    method = method_match.group(1) if method_match else ""
    path_value = info.get("路径", "")
    source_reference = path.relative_to(source_root).as_posix()
    interface_id_value = _NORMALIZED_INTERFACE_IDS.get(source_reference, source_interface_id)
    titles = _section_titles(lines)
    current_contract = _has_any(
        text,
        ("当前实现", "当前源码行为", "尚未实现", "兼容接口", "保留的兼容性缺陷"),
    )
    legacy_contract = _has_any(text, ("保留的兼容性缺陷", "当前HTTP方法仍为GET")) or (
        method == "GET" and "当前实现" in info.get("方法", "")
    )
    compatibility_reference = "兼容接口" in text or "兼容性缺陷" in text
    lifecycle = "current"
    contract_role = "observed"
    compatibility_group = None
    compatibility_of = None
    if interface_id_value == "UPLOAD-003":
        lifecycle = "legacy_compatibility"
        contract_role = "observed_legacy"
        compatibility_group = "UPLOAD-BLOG-DELETE"
        compatibility_of = "UPLOAD-005"
    elif interface_id_value == "UPLOAD-005":
        lifecycle = "recommended"
        contract_role = "target_recommended"
        compatibility_group = "UPLOAD-BLOG-DELETE"
        compatibility_of = "UPLOAD-003"
    notes: list[str] = []
    if current_contract:
        notes.append("文档包含当前实现说明，评测时需区分 observed_contract 与 target_contract。")
    if legacy_contract:
        notes.append("文档描述的是旧兼容实现，不能与推荐接口合并计数。")
    elif compatibility_reference:
        notes.append("文档引用了兼容旧接口，需与旧接口建立关系后再确定评测口径。")
    if interface_id_value != source_interface_id:
        notes.append(f"评测目录已将源文档编号 {source_interface_id} 规范化为 {interface_id_value}。")
    if not any("验收标准" in title for title in titles):
        notes.append("缺少独立的验收标准章节，候选 Test Point 仍需人工确认。")
    if not any("失败场景" in title for title in titles):
        notes.append("缺少独立的失败场景章节，负向点由正文关键词推导，仅作为候选。")
    baseline_points = points_for_interface(interface_id_value)
    operation = {
        "operation_id": interface_id_value,
        "method": method if method in _METHODS else None,
        "path": path_value or None,
        "source_reference": source_reference,
        "annotation_status": "draft",
        "points": baseline_points or _candidate_points(interface_id_value, text, info, titles),
        "notes": " ".join(notes) if notes else None,
        "metadata": {
            "title": _first_heading(lines, 1),
            "source_interface_id": source_interface_id,
            "baseline_operation_id": BASELINE_INTERFACE_TO_OPERATION.get(interface_id_value),
            "permission": info.get("权限"),
            "content_type": info.get("Content-Type"),
            "section_titles": titles,
            "current_contract": current_contract,
            "legacy_contract": legacy_contract,
            "compatibility_reference": compatibility_reference,
            "lifecycle": lifecycle,
            "contract_role": contract_role,
            "compatibility_group": compatibility_group,
            "compatibility_of": compatibility_of,
        },
    }
    return operation


def _numbering_audit(operations: list[dict[str, Any]]) -> list[dict[str, str]]:
    grouped: dict[str, list[int]] = {}
    for operation in operations:
        match = re.match(r"^(.*)-(\d+)$", operation["operation_id"])
        if not match:
            continue
        grouped.setdefault(match.group(1), []).append(int(match.group(2)))
    issues: list[dict[str, str]] = []
    for prefix, values in sorted(grouped.items()):
        unique = sorted(set(values))
        excluded_ids = {
            interface_id
            for exclusion in _SCOPE_EXCLUSIONS
            if exclusion["domain"] == prefix
            for interface_id in exclusion["interface_ids"]
        }
        first_in_scope = next((value for value in unique if f"{prefix}-{value:03d}" not in excluded_ids), None)
        if first_in_scope is not None and first_in_scope > 1 and not excluded_ids:
            issues.append(
                {
                    "type": "numbering_gap",
                    "severity": "warning",
                    "message": f"{prefix} 编号从 {unique[0]:03d} 开始，未在文档目录中发现更早编号。",
                }
            )
        missing = [
            str(value)
            for value in range(unique[0], unique[-1] + 1)
            if value not in unique and f"{prefix}-{value:03d}" not in excluded_ids
        ] if unique else []
        if missing:
            issues.append(
                {
                    "type": "numbering_gap",
                    "severity": "warning",
                    "message": f"{prefix} 中间缺少编号：{', '.join(missing)}。",
                }
            )
    return issues


def build_catalog(source_dir: Path, *, dataset_id: str = "hm_dianping_api_requirements_v1") -> dict[str, Any]:
    source_root = source_dir.expanduser().resolve()
    files = sorted(source_root.rglob("*.md"))
    operations = [parse_requirement_file(path, source_root) for path in files]
    by_id: dict[str, list[str]] = {}
    source_by_id: dict[str, list[str]] = {}
    for operation in operations:
        by_id.setdefault(operation["operation_id"], []).append(operation["source_reference"])
        source_by_id.setdefault(operation["metadata"]["source_interface_id"], []).append(operation["source_reference"])
    issues = _numbering_audit(operations)
    for interface_id, references in sorted(by_id.items()):
        if len(references) > 1:
            issues.append(
                {
                    "type": "duplicate_interface_id",
                    "severity": "error",
                    "message": f"{interface_id} 出现在：{', '.join(references)}。",
                }
            )
    compatibility_operations = [
        operation
        for operation in operations
        if operation["metadata"]["legacy_contract"] or operation["metadata"]["compatibility_reference"]
    ]
    if compatibility_operations:
        references = ", ".join(
            f"{operation['operation_id']} ({operation['source_reference']})" for operation in compatibility_operations
        )
        issues.append(
            {
                "type": "legacy_contract",
                "severity": "warning",
                "message": f"发现兼容接口关系，需人工确认新旧口径：{references}。",
            }
        )
    missing_acceptance = [
        operation["source_reference"]
        for operation in operations
        if not any("验收标准" in title for title in operation["metadata"]["section_titles"])
    ]
    missing_failure = [
        operation["source_reference"]
        for operation in operations
        if not any("失败场景" in title for title in operation["metadata"]["section_titles"])
    ]
    current_contract = [
        operation["source_reference"] for operation in operations if operation["metadata"]["current_contract"]
    ]
    legacy_contract = [
        operation["source_reference"] for operation in operations if operation["metadata"]["legacy_contract"]
    ]
    compatibility_reference = [
        operation["source_reference"]
        for operation in operations
        if operation["metadata"]["compatibility_reference"]
    ]
    source_collisions = {
        interface_id: references for interface_id, references in source_by_id.items() if len(references) > 1
    }
    return {
        "dataset_id": dataset_id,
        "version": "1.0.0",
        "source": "local-only:hm-dianping/docs/api",
        "annotation_status": "draft",
        "operations": operations,
        "audit": {
            "total_documents": len(files),
            "unique_interface_ids": len(by_id),
            "duplicate_interface_ids": sorted(interface_id for interface_id, refs in by_id.items() if len(refs) > 1),
            "source_interface_id_collisions": source_collisions,
            "normalization_changes": [
                {
                    "source_reference": operation["source_reference"],
                    "from": operation["metadata"]["source_interface_id"],
                    "to": operation["operation_id"],
                }
                for operation in operations
                if operation["metadata"]["source_interface_id"] != operation["operation_id"]
            ],
            "issues": issues,
            "structure": {
                "missing_acceptance_documents": missing_acceptance,
                "missing_failure_documents": missing_failure,
                "current_contract_documents": current_contract,
                "legacy_contract_documents": legacy_contract,
                "compatibility_reference_documents": compatibility_reference,
            },
            "scope_exclusions": _SCOPE_EXCLUSIONS,
        },
        "notes": "候选点由需求文档结构化提取，仅用于人工标注起稿；未完成确认前不得用于发布质量数字。",
    }


def write_catalog(source_dir: Path, output_path: Path, *, dataset_id: str = "hm_dianping_api_requirements_v1") -> dict[str, Any]:
    catalog = build_catalog(source_dir, dataset_id=dataset_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Markdown 接口需求文档生成 Ground Truth 候选目录")
    parser.add_argument("--source", required=True, type=Path, help="接口需求文档目录")
    parser.add_argument("--output", required=True, type=Path, help="输出 YAML 目录")
    args = parser.parse_args()
    catalog = write_catalog(args.source, args.output)
    audit = catalog["audit"]
    print(f"已处理 {audit['total_documents']} 份文档，得到 {audit['unique_interface_ids']} 个接口编号。")
    for issue in audit["issues"]:
        print(f"[{issue['severity']}] {issue['message']}")


if __name__ == "__main__":
    main()
