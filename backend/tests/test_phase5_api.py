from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app

from tests.test_phase1 import project_payload
from tests.test_phase3 import openapi_source


def test_cases_validate_save_and_review_api(tmp_path):
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
    points = client.post(
        f"/api/projects/{project_id}/test-points/generate",
        json={"requirement_id": "REQ-GET-ITEM-001"},
    ).json()["points"]
    point = points[0]
    evidence_id = point["evidence_refs"][0]
    case = {
        "case_id": "CASE-API-1",
        "requirement_id": "REQ-GET-ITEM-001",
        "test_point_ids": [point["point_id"]],
        "title": "API valid request",
        "category": "positive",
        "priority": "high",
        "steps": ["Send the request"],
        "expected_behavior": "The documented response is returned.",
        "request": {
            "method": "GET",
            "path": "/items/{item_id}",
            "path_params": {"item_id": 1},
        },
        "assertions": [
            {
                "assertion_id": "ASSERT-API-1",
                "type": "status_code",
                "expected": 200,
                "evidence_refs": [evidence_id],
            }
        ],
        "evidence_refs": [evidence_id],
    }
    validated = client.post(
        f"/api/projects/{project_id}/cases/validate",
        json={"case": case},
    )
    assert validated.status_code == 200
    assert validated.json() == {"valid": True, "errors": []}

    invalid_case = deepcopy(case)
    invalid_case["assertions"][0]["operator"] = "approximately"
    invalid = client.post(
        f"/api/projects/{project_id}/cases/validate",
        json={"case": invalid_case},
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert "unsupported assertion operator approximately" in invalid.json()["errors"][0]

    case_set = {
        "requirement_id": "REQ-GET-ITEM-001",
        "test_point_ids": [point["point_id"]],
        "cases": [case],
    }
    assert client.post(f"/api/projects/{project_id}/cases/save", json=case_set).status_code == 200
    reviewed = client.post(
        f"/api/projects/{project_id}/cases/review",
        json={"requirement_id": "REQ-GET-ITEM-001", "cases": case_set},
    )
    assert reviewed.status_code == 200
    review_output = reviewed.json()["reviewer_output"]
    assert review_output["missing_test_point_ids"]
    assert "score" not in review_output
    assert client.get(f"/api/projects/{project_id}/cases/REQ-GET-ITEM-001").status_code == 200
