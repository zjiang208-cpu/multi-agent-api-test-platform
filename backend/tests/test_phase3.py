from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app

from tests.test_phase1 import project_payload


def openapi_source(tmp_path):
    source = tmp_path / "openapi.yaml"
    source.write_text(
        """
openapi: 3.0.3
info: {title: Demo, version: '1'}
paths:
  /items/{item_id}:
    get:
      operationId: get-item
      summary: Get item
      parameters:
        - {name: item_id, in: path, required: true, schema: {type: integer, minimum: 1}}
      responses:
        '200': {description: ok}
        '404': {description: missing}
""",
        encoding="utf-8",
    )
    return source


def test_requirement_build_is_openapi_first_and_persistent(tmp_path):
    source = openapi_source(tmp_path)
    payload = project_payload()
    payload["settings"]["openapi_sources"] = [str(source)]
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    project = client.post("/api/projects", json=payload).json()
    project_id = project["project_id"]
    assert client.post(f"/api/projects/{project_id}/operations/discover", json={}).status_code == 200

    response = client.post(
        f"/api/projects/{project_id}/requirements/build",
        json={"operation_id": "get-item"},
    )
    assert response.status_code == 200
    body = response.json()
    requirement = body["requirement"]
    assert requirement["requirement_id"] == "REQ-GET-ITEM-001"
    assert requirement["api"]["method"] == "GET"
    assert any("item_id" in value for value in requirement["business_rules"])
    assert any(ref["source_type"] == "openapi" for ref in requirement["evidence_refs"])
    assert body["evidence"]["provider_status"]["source_code"].startswith("not_configured:")
    assert client.get(
        f"/api/projects/{project_id}/requirements/REQ-GET-ITEM-001"
    ).status_code == 200


def test_optional_java_source_evidence_is_bounded_and_relative(tmp_path):
    source = openapi_source(tmp_path)
    java_root = tmp_path / "java"
    controller = java_root / "demo" / "ItemController.java"
    controller.parent.mkdir(parents=True)
    controller.write_text(
        """
@RestController
@RequestMapping("/items")
class ItemController {
    @GetMapping("/{item_id}")
    Object getItem() { return null; }
}
""",
        encoding="utf-8",
    )
    payload = project_payload()
    payload["settings"]["openapi_sources"] = [str(source)]
    payload["settings"]["source_workspace"] = str(java_root)
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    project_id = client.post("/api/projects", json=payload).json()["project_id"]
    client.post(f"/api/projects/{project_id}/operations/discover", json={})

    response = client.post(
        f"/api/projects/{project_id}/requirements/build",
        json={"operation_id": "get-item", "include_optional_evidence": True},
    )
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    source_facts = [fact for fact in evidence["facts"] if fact["source_type"] == "source_code"]
    assert source_facts
    assert source_facts[0]["reference"] == "source:demo/ItemController.java"
    assert "GetMapping" in source_facts[0]["safe_excerpt"]
    assert not source_facts[0]["reference"].startswith("source:") or ":\\" not in source_facts[0]["reference"]
