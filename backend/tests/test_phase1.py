from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app


def project_payload(name: str = "Demo API") -> dict:
    return {
        "name": name,
        "description": "Phase 1 project",
        "settings": {
            "requirement_sources": ["examples/requirements/demo.yaml"],
            "openapi_sources": [],
            "source_workspace": None,
            "sut_target": {
                "base_url": "http://127.0.0.1:8081",
                "timeout_seconds": 5,
                "allow_redirects": False,
                "verify_tls": True,
                "auth_ref": "env:DEMO_API_AUTH",
            },
            "database": {
                "enabled": False,
                "dialect": None,
                "dsn_ref": None,
                "readonly": True,
                "schema": None,
                "allowed_tables": [],
            },
            "llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "model": None,
                "api_key_ref": None,
                "base_url": None,
                "call_budget": 20,
            },
        },
    }


def test_health_and_config_are_safe(tmp_path):
    settings = AppSettings(data_dir=tmp_path, llm_api_key_ref="env:SECRET_REF")
    client = TestClient(create_app(settings=settings))

    assert client.get("/health").json() == {
        "status": "ok",
        "service": "api-test-platform",
    }
    config = client.get("/api/config/status")
    assert config.status_code == 200
    assert config.json()["execution_policy"]["credentials_exposed"] is False
    assert "SECRET_REF" not in config.text


def test_project_crud_is_persistent_and_rejects_secret_fields(tmp_path):
    settings = AppSettings(data_dir=tmp_path)
    first_client = TestClient(create_app(settings=settings))

    created = first_client.post("/api/projects", json=project_payload())
    assert created.status_code == 201
    project = created.json()
    project_id = project["project_id"]
    assert project["settings"]["sut_target"]["auth_ref"] == "env:DEMO_API_AUTH"

    listed = first_client.get("/api/projects")
    assert listed.status_code == 200
    assert listed.json()[0]["project_id"] == project_id

    duplicate = first_client.post("/api/projects", json=project_payload())
    assert duplicate.status_code == 409

    secret_payload = project_payload("Secret Attempt")
    secret_payload["settings"]["sut_target"]["password"] = "must-not-be-accepted"
    rejected = first_client.post("/api/projects", json=secret_payload)
    assert rejected.status_code == 422

    second_client = TestClient(create_app(settings=settings))
    assert second_client.get(f"/api/projects/{project_id}").status_code == 200

    updated = second_client.patch(
        f"/api/projects/{project_id}",
        json={"description": "updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "updated"

    deleted = second_client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204
    assert second_client.get(f"/api/projects/{project_id}").status_code == 404
