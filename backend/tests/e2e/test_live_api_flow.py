from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


pytestmark = pytest.mark.e2e

API_BASE_URL = os.getenv("E2E_API_BASE_URL", "http://127.0.0.1:8000")
SUT_BASE_URL = os.getenv("E2E_SUT_BASE_URL", "http://127.0.0.1:18281")
PROJECT_NAME = f"e2e-sample-{uuid4().hex[:8]}"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_OPENAPI = REPOSITORY_ROOT / "examples" / "requirements" / "sample-openapi.yaml"


def project_payload() -> dict:
    return {
        "name": PROJECT_NAME,
        "description": "Black-box acceptance project; removed after the test.",
        "settings": {
            "requirement_sources": [],
            "openapi_sources": [],
            "source_workspace": None,
            "sut_target": {
                "base_url": SUT_BASE_URL,
                "timeout_seconds": 5,
                "allow_redirects": False,
                "verify_tls": True,
                "auth_ref": None,
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


def test_live_project_document_and_operation_flow() -> None:
    assert SAMPLE_OPENAPI.is_file(), f"sample contract not found: {SAMPLE_OPENAPI}"

    with httpx.Client(timeout=20, follow_redirects=False) as api_client:
        api_health = api_client.get(f"{API_BASE_URL}/health")
        assert api_health.status_code == 200
        assert api_health.json()["status"] == "ok"

        sut_health = api_client.get(f"{SUT_BASE_URL}/health")
        assert sut_health.status_code == 200
        assert sut_health.json()["status"] == "ok"

        sut_response = api_client.get(f"{SUT_BASE_URL}/items/1")
        assert sut_response.status_code == 200
        assert sut_response.json()["success"] is True

        created = api_client.post(
            f"{API_BASE_URL}/api/projects",
            json=project_payload(),
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["project_id"]

        try:
            contract = SAMPLE_OPENAPI.read_text(encoding="utf-8")
            discovered = api_client.post(
                f"{API_BASE_URL}/api/projects/{project_id}/requirement-documents/ingest-and-discover",
                json={
                    "filename": SAMPLE_OPENAPI.name,
                    "content": contract,
                },
            )
            assert discovered.status_code == 200, discovered.text
            body = discovered.json()
            assert body["document"]["project_id"] == project_id
            assert {item["operation_id"] for item in body["operations"]} == {
                "get-item",
                "create-item",
            }

            listed = api_client.get(f"{API_BASE_URL}/api/projects/{project_id}/operations")
            assert listed.status_code == 200
            assert len(listed.json()) == 2
        finally:
            deleted = api_client.delete(f"{API_BASE_URL}/api/projects/{project_id}")
            assert deleted.status_code == 204, deleted.text
