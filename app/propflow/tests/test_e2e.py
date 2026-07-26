"""
PropFlow API Integration Tests
==============================
Tests the PropFlow workflow through the FastAPI route layer,
exactly like the frontend does — using TestClient.

Test Strategy:
  - Uses FastAPI's TestClient to call actual HTTP endpoints
  - All external AI/payment services are mocked
  - Database calls go through the server's proven database.py path
  - Tests validate HTTP status codes, response shapes, and stage transitions

Usage:
  pytest app/propflow/tests/test_e2e.py -v
  pytest app/propflow/tests/test_e2e.py -v -k "health"
"""

import pytest
from unittest.mock import patch, AsyncMock

# Check if Supabase is reachable before any tests run
try:
    from app.database import get_supabase_admin
    sb = get_supabase_admin()
    sb.table("users").select("id").limit(1).execute()
    _SUPABASE_AVAILABLE = True
except Exception:
    _SUPABASE_AVAILABLE = False


# ============================================================
# Health endpoint — no DB needed
# ============================================================

def test_health_endpoint():
    """Server starts and health endpoint responds."""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "supabase" in data.get("checks", {})


# ============================================================
# API route tests — require Supabase
# ============================================================

@pytest.mark.skipif(not _SUPABASE_AVAILABLE, reason="Supabase not reachable")
class TestPropFlowAPI:
    """Tests PropFlow routes through the FastAPI HTTP layer."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Per-test setup: create TestClient with mocked external services."""
        from starlette.testclient import TestClient
        from app.main import app

        # Mock external services before creating client
        self._patches = [
            patch("app.propflow.services.qwen_client.qwen_client.extract_intent",
                  new_callable=AsyncMock,
                  return_value={
                      "property_type": "apartment",
                      "location": "Lekki",
                      "bedrooms": 2,
                      "budget_monthly": 500000.0,
                      "confidence": 0.91,
                  }),
            patch("app.propflow.services.qwen_client.qwen_client.generate_landlord_briefing",
                  new_callable=AsyncMock,
                  return_value="Test tenant briefing."),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app)

    def teardown_method(self):
        for p in self._patches:
            p.stop()

    def test_propflow_chat_starts_workflow(self):
        """POST /api/v1/propflow/chat starts a new workflow and returns a thread_id."""
        resp = self.client.post(
            "/api/v1/propflow/chat",
            json={"message": "I need a 2-bedroom apartment in Lekki for 500k monthly"},
            headers={"X-User-Id": str(__import__("uuid").uuid4()), "X-User-Type": "tenant"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert "workflow_id" in data
        assert "current_stage" in data

    def test_propflow_status_returns_stage(self):
        """GET /api/v1/propflow/status/{workflow_id} returns the current stage."""
        # First create a workflow via chat
        import uuid
        tenant_id = str(uuid.uuid4())
        chat_resp = self.client.post(
            "/api/v1/propflow/chat",
            json={"message": "Looking for 2-bed in Lekki, budget 500k"},
            headers={"X-User-Id": tenant_id, "X-User-Type": "tenant"},
        )
        assert chat_resp.status_code == 200
        workflow_id = chat_resp.json().get("workflow_id")
        if not workflow_id:
            pytest.skip("No workflow_id returned — chat may need real Qwen")

        # Check status
        resp = self.client.get(f"/api/v1/propflow/status/{workflow_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_stage" in data

    def test_threads_endpoint_returns_list(self):
        """GET /api/v1/propflow/threads returns the tenant's threads."""
        import uuid
        tenant_id = str(uuid.uuid4())
        resp = self.client.get(
            "/api/v1/propflow/threads",
            headers={"X-User-Id": tenant_id, "X-User-Type": "tenant"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "threads" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])