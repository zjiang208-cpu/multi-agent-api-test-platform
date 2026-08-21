from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.core.config import AppSettings
from app.models.documents import StoredRequirementDocument
from app.models.projects import TestProject
from app.projects.service import ProjectService
from app.projects.store import ProjectStore
from app.requirements.api_discovery import ApiDiscoveryService
from app.requirements.document_parser import parse_requirement_document
from app.requirements.document_store import RequirementDocumentStore
from app.requirements.operation_store import OperationStore
from app.workflow.fingerprint import requirement_fingerprint
from app.workflow.service import WorkflowService
from evals.input_audit import audit_input_payload
from evals.models import EvalSample


BASELINE_DOCUMENTS = {
    "get-shop-id": "shop/get-shop.md",
    "get-shop-of-type": "shop/list-shops-by-type.md",
    "get-shop-type-list": "shop-type/list-shop-types.md",
    "get-voucher-id": "voucher/get-voucher.md",
    "get-blog-hot": "blog/list-hot-blogs.md",
    "get-user-me": "user/get-current-user.md",
    "get-blog-id": "blog/get-blog.md",
    "post-shop-type": "shop-type/create-shop-type.md",
    "put-user-info": "user/update-user-info.md",
    "delete-shop-type-id": "shop-type/delete-shop-type.md",
}


def _load_source_project(data_dir: Path, project_id: str) -> TestProject:
    project = ProjectStore(data_dir).get(project_id)
    if project is None:
        raise ValueError(f"找不到源项目：{project_id}")
    if not project.settings.llm.enabled:
        raise ValueError("源项目未启用 LLM 配置")
    return project


def _prepare_isolated_project(
    *, source_project: TestProject, data_dir: Path
) -> tuple[TestProject, ProjectService]:
    store = ProjectStore(data_dir)
    project_id = "project-eval-baseline-v1"
    current = store.get(project_id)
    now = datetime.now(timezone.utc)
    project = TestProject(
        project_id=project_id,
        name="baseline_v1 本地离线评测",
        description="隔离生成评测快照，不进入平台业务项目。",
        settings=source_project.settings,
        created_at=current.created_at if current else now,
        updated_at=now,
    )
    store.save(project)
    return project, ProjectService(store)


def _ingest_operation(
    *,
    data_dir: Path,
    project_id: str,
    runtime_session_id: str,
    document_path: Path,
    expected_operation_id: str,
) -> tuple[StoredRequirementDocument, str]:
    content = document_path.read_text(encoding="utf-8")
    parsed = parse_requirement_document(
        filename=document_path.name,
        data=content.encode("utf-8"),
        media_type="text/markdown",
    )
    document = StoredRequirementDocument.model_validate(
        parsed.model_dump(mode="json")
        | {"project_id": project_id, "runtime_session_id": runtime_session_id}
    )
    RequirementDocumentStore(data_dir, project_id).save(document)
    operations = [
        operation.model_copy(update={"runtime_session_id": runtime_session_id})
        for operation in ApiDiscoveryService().discover(document)
    ]
    if len(operations) != 1:
        operation_ids = [item.operation_id for item in operations]
        raise ValueError(f"{document_path.name} 应解析出 1 个接口，实际为 {operation_ids}")
    operation = operations[0]
    if operation.operation_id != expected_operation_id:
        raise ValueError(
            f"接口编号不一致：期望 {expected_operation_id}，实际 {operation.operation_id}"
        )
    OperationStore(data_dir, project_id).save_requirement_document_operations(
        document.document_id, operations
    )
    return document, content


def _safe_metadata(metadata: dict[str, str]) -> dict[str, str]:
    allowed_prefixes = (
        "llm_",
        "prompt_version",
        "nlu_prompt_version",
        "designer_prompt_version",
        "reviewer_prompt_version",
    )
    safe = {
        key: value
        for key, value in metadata.items()
        if key.startswith(allowed_prefixes)
    }
    safe.update(
        {
            "source": "local-redacted-workflow-snapshot",
            "execution_gate": "benchmark_auto_approval",
            "input_document": "provided",
        }
    )
    return safe


def _sample_payload(snapshot) -> dict[str, Any]:
    sample = EvalSample.from_workflow_snapshot(
        snapshot.model_dump(mode="json"),
        sample_id=f"baseline-v1-{snapshot.operation_id}-current",
        variant="current-prompt",
    )
    sample.metadata = _safe_metadata(snapshot.metadata)
    payload = {"samples": [sample.model_dump(mode="json", exclude_none=True)]}
    audit = audit_input_payload(payload)
    if audit["status"] != "ready":
        paths = [issue["path"] for issue in audit["issues"]]
        raise ValueError(f"脱敏审计未通过：{paths}")
    return payload


def _summary_entry(snapshot, sample_path: Path) -> dict[str, Any]:
    points = snapshot.test_points.points if snapshot.test_points else []
    cases = snapshot.final_cases.cases if snapshot.final_cases else []
    return {
        "operation_id": snapshot.operation_id,
        "status": snapshot.status,
        "workflow_id": snapshot.workflow_id,
        "test_point_count": len(points),
        "case_count": len(cases),
        "assertion_count": sum(len(case.assertions) for case in cases),
        "prompt_version": snapshot.metadata.get("prompt_version"),
        "sample": str(sample_path),
    }


def generate(args: argparse.Namespace) -> int:
    source_data_dir = args.source_data_dir.resolve()
    output_root = args.output_root.resolve()
    private_data_dir = output_root / "private-data"
    sample_dir = output_root / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)

    source_project = _load_source_project(source_data_dir, args.source_project_id)
    project, project_service = _prepare_isolated_project(
        source_project=source_project, data_dir=private_data_dir
    )
    workflow_service = WorkflowService(
        project_service, private_data_dir, AppSettings(data_dir=private_data_dir)
    )
    runtime_session_id = "runtime-eval-baseline-v1"
    selected = args.operation or list(BASELINE_DOCUMENTS)

    summary_path = output_root / "generation-summary.yaml"
    summary = (
        yaml.safe_load(summary_path.read_text(encoding="utf-8")) or {}
        if summary_path.exists()
        else {}
    )
    entries = {
        item["operation_id"]: item
        for item in summary.get("operations", [])
        if isinstance(item, dict) and item.get("operation_id")
    }

    for operation_id in selected:
        sample_path = sample_dir / f"{operation_id}-current-redacted.json"
        if sample_path.exists() and not args.force:
            print(f"SKIP {operation_id}: 已存在脱敏样本", flush=True)
            continue
        document_path = args.docs_root / BASELINE_DOCUMENTS[operation_id]
        if not document_path.is_file():
            raise FileNotFoundError(document_path)
        document, content = _ingest_operation(
            data_dir=private_data_dir,
            project_id=project.project_id,
            runtime_session_id=runtime_session_id,
            document_path=document_path,
            expected_operation_id=operation_id,
        )
        print(f"RUN {operation_id}: NLU", flush=True)
        snapshot = workflow_service.run_nlu(
            project.project_id,
            operation_id,
            input_document_id=document.document_id,
            input_document=content,
        )
        if snapshot.requirement is None:
            raise ValueError(f"{operation_id} 未生成 Requirement")
        workflow_service.approve_requirement(
            project.project_id,
            snapshot.workflow_id,
            requirement_id=snapshot.requirement.requirement_id,
            requirement_version=snapshot.requirement.version,
            requirement_fingerprint_value=requirement_fingerprint(snapshot.requirement),
        )
        print(f"RUN {operation_id}: Designer + Reviewer", flush=True)
        completed = workflow_service.continue_after_requirement_approval(
            project.project_id, snapshot.workflow_id
        )
        payload = _sample_payload(completed)
        sample_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        entries[operation_id] = _summary_entry(completed, sample_path)
        summary_payload = {
            "dataset_id": "baseline_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "isolation": "evals/reports 下的本地私有工作区；Git 忽略",
            "operations": [entries[key] for key in sorted(entries)],
        }
        summary_path.write_text(
            yaml.safe_dump(summary_payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        entry = entries[operation_id]
        print(
            f"DONE {operation_id}: {entry['test_point_count']} points, "
            f"{entry['case_count']} cases, {entry['assertion_count']} assertions",
            flush=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 baseline_v1 的隔离工作流快照与脱敏样本")
    parser.add_argument("--docs-root", type=Path, required=True)
    parser.add_argument("--source-data-dir", type=Path, default=Path("backend/.data"))
    parser.add_argument("--source-project-id", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("evals/reports/baseline_v1/generated"),
    )
    parser.add_argument("--operation", action="append", choices=list(BASELINE_DOCUMENTS))
    parser.add_argument("--force", action="store_true")
    return generate(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
