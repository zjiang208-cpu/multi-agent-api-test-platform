from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.core.config import AppSettings
from app.main import create_app
from app.models.contracts import OperationContract
from app.models.queue import ApiProcessingItem, ApiProcessingQueue
from app.models.requirements import RequirementDocument
from app.requirements.document_parser import MAX_DOCUMENT_BYTES
from app.requirements.openapi import OpenApiLoader, SourceLoadError
from app.requirements.yaml_store import YamlArtifactStore
from app.workflow.queue_store import QueueStore

from tests.test_phase1 import project_payload


def test_openapi_discovery_and_operation_persistence(tmp_path):
    source = tmp_path / "openapi.yaml"
    source.write_text(
        """
openapi: 3.0.3
info: {title: Demo, version: '1'}
paths:
  /items/{item_id}:
    get:
      operationId: get-item
      parameters:
        - {name: item_id, in: path, required: true, schema: {type: integer, minimum: 1}}
      responses:
        '200': {description: ok}
  /items:
    post:
      responses:
        '201': {description: created}
""",
        encoding="utf-8",
    )
    payload = project_payload()
    payload["settings"]["openapi_sources"] = [str(source)]
    payload["settings"]["requirement_sources"] = []
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    created = client.post("/api/projects", json=payload)
    assert created.status_code == 201
    project_id = created.json()["project_id"]

    discovered = client.post(f"/api/projects/{project_id}/operations/discover", json={})
    assert discovered.status_code == 200
    body = discovered.json()
    assert {item["operation_id"] for item in body["operations"]} == {"get-item", "post-items"}
    assert body["source_status"][str(source)].startswith("healthy:")
    assert client.get(f"/api/projects/{project_id}/operations").json()[0]["operation_id"] == "get-item"


def test_operation_yaml_ingest_persists_document_for_workflow_queue(tmp_path):
    settings = AppSettings(data_dir=tmp_path / "data")
    client = TestClient(create_app(settings=settings))
    created = client.post("/api/projects", json=project_payload())
    assert created.status_code == 201
    project_id = created.json()["project_id"]
    content = """
operation:
  id: get-item
  method: GET
  path: /items/{id}
  summary: Get item
request:
  parameters: []
response:
  scenarios:
    - id: success
      condition: item exists
      http_status: 200
""".strip()

    discovered = client.post(
        f"/api/projects/{project_id}/requirement-documents/ingest-and-discover",
        json={"filename": "operation-get-item.yaml", "content": content},
    )
    assert discovered.status_code == 200
    body = discovered.json()
    document_id = body["document"]["document_id"]
    assert body["document"]["detected_kind"] == "operation_contract"
    assert len(body["operations"]) == 1
    assert body["operations"][0]["source_document_id"] == document_id

    queue = client.post(
        f"/api/projects/{project_id}/processing-queues",
        json={"source_document_id": document_id, "operation_ids": ["get-item"]},
    )
    assert queue.status_code == 200
    listed = client.get(f"/api/projects/{project_id}/processing-queues")
    assert listed.status_code == 200
    assert [item["run_id"] for item in listed.json()] == [queue.json()["run_id"]]

    restarted_client = TestClient(create_app(settings=settings))
    restarted_list = restarted_client.get(f"/api/projects/{project_id}/processing-queues")
    assert restarted_list.status_code == 200
    assert restarted_list.json() == []
    restarted_documents = restarted_client.get(
        f"/api/projects/{project_id}/requirement-documents"
    )
    assert restarted_documents.status_code == 200
    assert restarted_documents.json() == []
    restarted_operations = restarted_client.get(f"/api/projects/{project_id}/operations")
    assert restarted_operations.status_code == 200
    assert restarted_operations.json() == []

    # Restarting hides stale working data from automatic recovery; it does not
    # destroy persisted artifacts that may still be useful for audit/debugging.
    persisted = restarted_client.get(
        f"/api/projects/{project_id}/processing-queues/{queue.json()['run_id']}"
    )
    assert persisted.status_code == 200


def test_markdown_table_requirement_discovers_one_deduplicated_operation(tmp_path):
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    created = client.post("/api/projects", json=project_payload())
    assert created.status_code == 201
    project_id = created.json()["project_id"]
    content = """
# 查询商铺类型列表

## 1. 基本信息

| 项目 | 内容 |
|---|---|
| 接口编号 | `ITEM-CATEGORY-001` |
| 方法 | `GET`（当前实现） |
| 路径 | `/item-category/list` |
| 权限 | 公开 |

## 2. 调用示例

GET /item-category/list?current=1
""".strip()

    discovered = client.post(
        f"/api/projects/{project_id}/requirement-documents/ingest-and-discover",
        json={"filename": "list-item-categories.md", "content": content},
    )

    assert discovered.status_code == 200
    body = discovered.json()
    assert len(body["operations"]) == 1
    operation = body["operations"][0]
    assert operation["operation_id"] == "get-item-category-list"
    assert operation["method"] == "GET"
    assert operation["path"] == "/item-category/list"
    assert operation["contract_metadata"]["source_format"] == "markdown_table"
    assert operation["contract_metadata"]["document_operation_id"] == "ITEM-CATEGORY-001"


def test_uploading_second_requirement_document_retains_first_document_and_operations(tmp_path):
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    created = client.post("/api/projects", json=project_payload())
    assert created.status_code == 201
    project_id = created.json()["project_id"]

    def upload(filename: str, number: str, path: str):
        content = f"""
# {number} 接口需求

| 项目 | 内容 |
|---|---|
| 接口编号 | `{number}` |
| 方法 | `GET` |
| 路径 | `{path}` |
| 权限 | 公开 |
""".strip()
        return client.post(
            f"/api/projects/{project_id}/requirement-documents/ingest-and-discover",
            json={"filename": filename, "content": content},
        )

    first = upload("first.md", "FIRST-001", "/first/{id}")
    assert first.status_code == 200
    first_body = first.json()
    first_document_id = first_body["document"]["document_id"]
    first_operation_id = first_body["operations"][0]["operation_id"]

    second = upload("second.md", "SECOND-001", "/second/{id}")
    assert second.status_code == 200
    second_body = second.json()
    second_document_id = second_body["document"]["document_id"]

    documents = client.get(f"/api/projects/{project_id}/requirement-documents")
    assert documents.status_code == 200
    assert {item["document_id"] for item in documents.json()} == {
        first_document_id,
        second_document_id,
    }

    operations = client.get(f"/api/projects/{project_id}/operations")
    assert operations.status_code == 200
    assert {item["path"] for item in operations.json()} == {"/first/{id}", "/second/{id}"}
    assert {item["source_document_id"] for item in operations.json()} == {
        first_document_id,
        second_document_id,
    }
    assert len(second_body["operations"]) == 2

    restored_first = client.get(
        f"/api/projects/{project_id}/requirement-documents/{first_document_id}"
    )
    assert restored_first.status_code == 200
    assert restored_first.json()["filename"] == "first.md"

    queue = client.post(
        f"/api/projects/{project_id}/processing-queues",
        json={"source_document_id": first_document_id, "operation_ids": [first_operation_id]},
    )
    assert queue.status_code == 200


def test_processing_queue_accepts_only_one_operation_per_flow(tmp_path):
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    created = client.post("/api/projects", json=project_payload())
    assert created.status_code == 201

    response = client.post(
        f"/api/projects/{created.json()['project_id']}/processing-queues",
        json={"source_document_id": "document", "operation_ids": ["first", "second"]},
    )

    assert response.status_code == 422
    project_cases = client.get(f"/api/projects/{created.json()['project_id']}/cases/final")
    assert project_cases.status_code == 200
    assert project_cases.json() == []


def test_blocked_processing_queue_can_be_skipped_through_api(tmp_path):
    settings = AppSettings(data_dir=tmp_path / "data")
    client = TestClient(create_app(settings=settings))
    created = client.post("/api/projects", json=project_payload())
    assert created.status_code == 201
    project_id = created.json()["project_id"]
    queue = ApiProcessingQueue(
        run_id="queue-blocked-api",
        project_id=project_id,
        source_document_id="document-blocked-api",
        selected_api_ids=["blocked-item"],
        status="BLOCKED",
        items=[
            ApiProcessingItem(
                api_operation_id="blocked-item",
                order=1,
                status="BLOCKED",
                current_stage="REVIEWER",
                workflow_id="workflow-blocked-api",
                final_case_set_id="final-blocked-api",
                error_message="review gap",
            )
        ],
    )
    QueueStore(settings.resolved_data_dir(), project_id).save(queue)

    response = client.post(
        f"/api/projects/{project_id}/processing-queues/{queue.run_id}/skip-current",
        json={"reason": "defer for later review"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "SKIPPED"
    assert response.json()["items"][0]["status"] == "SKIPPED"
    assert response.json()["items"][0]["workflow_id"] == "workflow-blocked-api"


def test_requirement_document_upload_is_bounded(tmp_path):
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))

    response = client.post(
        "/api/requirement-documents/parse",
        files={
            "file": (
                "oversized.txt",
                b"x" * (MAX_DOCUMENT_BYTES + 1),
                "text/plain",
            )
        },
    )

    assert response.status_code == 400
    assert "exceeds 10 MB" in response.json()["error"]["message"]


def test_remote_openapi_download_stops_at_size_limit(monkeypatch):
    class Response:
        headers = {}

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def iter_bytes():
            yield b"123"
            yield b"456"

    class Stream:
        def __enter__(self):
            return Response()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.requirements.openapi.httpx.stream", lambda *args, **kwargs: Stream())

    with pytest.raises(SourceLoadError, match="exceeds configured size limit"):
        OpenApiLoader(allow_remote_sources=True, max_document_bytes=5).discover(
            "https://example.invalid/openapi.yaml"
        )


def test_yaml_store_round_trip_and_path_validation(tmp_path):
    operation = OperationContract(
        operation_id="get-item",
        method="GET",
        path="/items/{item_id}",
        responses=[{"status_code": 200, "description": "ok"}],
    )
    store = YamlArtifactStore(tmp_path / "artifacts")
    path = store.save("operations", operation.operation_id, operation)
    restored = store.load("operations", operation.operation_id, OperationContract)
    assert path.suffix == ".yaml"
    assert restored.operation_key == "GET /items/{item_id}"

    requirement = RequirementDocument(
        requirement_id="REQ-GET-ITEM-001",
        api=restored,
    )
    store.save("requirements", requirement.requirement_id, requirement)
    assert (
        store.load("requirements", requirement.requirement_id, RequirementDocument).api.operation_id
        == "get-item"
    )

    try:
        store.path_for("../outside", "bad")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe artifact segment was accepted")
