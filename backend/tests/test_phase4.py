from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app

from tests.test_phase3 import openapi_source
from tests.test_phase1 import project_payload


def test_test_points_cover_required_params_boundaries_responses_and_persist(tmp_path):
    source = openapi_source(tmp_path)
    payload = project_payload()
    payload["settings"]["openapi_sources"] = [str(source)]
    client = TestClient(create_app(settings=AppSettings(data_dir=tmp_path / "data")))
    project_id = client.post("/api/projects", json=payload).json()["project_id"]
    client.post(f"/api/projects/{project_id}/operations/discover", json={})
    client.post(
        f"/api/projects/{project_id}/requirements/build",
        json={"operation_id": "get-item"},
    )

    response = client.post(
        f"/api/projects/{project_id}/test-points/generate",
        json={"requirement_id": "REQ-GET-ITEM-001"},
    )
    assert response.status_code == 200
    body = response.json()
    points = body["points"]
    titles = [item["title"] for item in points]
    assert any("valid request" in title for title in titles)
    assert any("missing required path parameter 'item_id'" in title for title in titles)
    assert any("minimum=1" in title for title in titles)
    assert any("status 200" in title for title in titles)
    assert any("status 404" in title for title in titles)
    assert len({item["point_id"] for item in points}) == len(points)
    assert all(item["requirement_id"] == "REQ-GET-ITEM-001" for item in points)
    assert all(item["evidence_refs"] for item in points)

    persisted = client.get(
        f"/api/projects/{project_id}/test-points/REQ-GET-ITEM-001"
    )
    assert persisted.status_code == 200
    assert len(persisted.json()["points"]) == len(points)

