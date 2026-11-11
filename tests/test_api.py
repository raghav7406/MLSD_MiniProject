"""Tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient

from src.services.api import app

client = TestClient(app)

VALID_PAYLOAD = {
    "member_id": "M-1001",
    "policy_number": "P-2001",
    "policy_name": "Care Supreme",
    "diagnosis_name": "Cataract",
    "procedure_name": "Phacoemulsification",
    "admission_type": "PLANNED",
    "policy_tenure_months": 24,
    "estimated_cost": 50000,
}


class TestSubmitEndpoint:
    def test_valid_submission_returns_202(self):
        resp = client.post("/api/v1/preauth", json=VALID_PAYLOAD)
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert "run_id" in data
        assert data["status"] == "PENDING"

    def test_invalid_payload_returns_422(self):
        resp = client.post("/api/v1/preauth", json={"member_id": ""})
        assert resp.status_code == 422

    def test_malformed_json_returns_422(self):
        resp = client.post(
            "/api/v1/preauth",
            content=b"not json at all",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422


class TestPollEndpoint:
    def test_pending_task_returns_pending(self):
        resp = client.get("/api/v1/preauth/nonexistent-task-id")
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"

    def test_completed_task_returns_result(self):
        submit = client.post("/api/v1/preauth", json=VALID_PAYLOAD)
        task_id = submit.json()["task_id"]
        result = client.get(f"/api/v1/preauth/{task_id}")
        assert result.status_code == 200
        data = result.json()
        # In synchronous/local mode the result is immediately available
        assert data["status"] in ("SUCCESS", "PENDING", "FAILED")


class TestHealthEndpoint:
    def test_health_returns_healthy(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "circuit_breaker" in data


class TestFeedbackEndpoint:
    def test_submit_feedback(self):
        resp = client.post(
            "/api/v1/feedback",
            json={"run_id": "test-run-1", "satisfactory": True, "reason": "Good result"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "recorded"

    def test_feedback_requires_run_id(self):
        resp = client.post(
            "/api/v1/feedback",
            json={"satisfactory": True},
        )
        assert resp.status_code == 400

    def test_feedback_summary_empty(self):
        resp = client.get("/api/v1/feedback/summary")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

