from fastapi.testclient import TestClient

from examples.sample_sut.main import app


def test_standalone_sample_sut_has_success_and_business_failure_envelopes():
    client = TestClient(app)
    success = client.get("/items/1")
    missing = client.get("/items/999")
    assert success.status_code == 200
    assert success.json()["success"] is True
    assert success.json()["data"]["id"] == 1
    assert missing.status_code == 200
    assert missing.json()["success"] is False

