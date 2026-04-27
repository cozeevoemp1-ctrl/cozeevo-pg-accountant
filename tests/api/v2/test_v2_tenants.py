"""Tests for GET /api/v2/app/tenants/search and GET /api/v2/app/tenants/{id}/dues."""
import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient

TEST_SECRET = "test-secret-abcdefghijklmnopqrstuvwxyz1234"
os.environ["SUPABASE_JWT_SECRET"] = TEST_SECRET

from main import app


def _make_jwt(role: str = "admin", phone: str = "+917845952289") -> str:
    return jwt.encode(
        {
            "sub": "user-uuid-123",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "phone": phone,
            "user_metadata": {"role": role, "org_id": 1},
        },
        TEST_SECRET,
        algorithm="HS256",
    )


# ── /tenants/search ────────────────────────────────────────────────────────

class TestTenantSearch:
    def test_search_by_name_returns_200(self):
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/search?q=kumar", headers=headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_search_by_room_number_returns_200(self):
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/search?q=205", headers=headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_empty_query_returns_400(self):
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/search?q=", headers=headers)
        assert r.status_code == 400

    def test_missing_query_param_returns_400(self):
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/search", headers=headers)
        assert r.status_code == 400

    def test_no_auth_returns_401(self):
        with TestClient(app) as client:
            r = client.get("/api/v2/app/tenants/search?q=kumar")
        assert r.status_code == 401

    def test_invalid_token_returns_401(self):
        with TestClient(app) as client:
            r = client.get(
                "/api/v2/app/tenants/search?q=kumar",
                headers={"Authorization": "Bearer invalid.token.here"},
            )
        assert r.status_code == 401

    def test_result_shape(self):
        """Each result must contain required keys with correct types."""
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/search?q=a", headers=headers)
        assert r.status_code == 200
        results = r.json()
        for item in results:
            assert "tenancy_id" in item
            assert "tenant_id" in item
            assert "name" in item
            assert "phone" in item
            assert "room_number" in item
            assert "building_code" in item
            assert "rent" in item
            assert "status" in item
            assert item["status"] in ("active", "no_show")

    def test_max_10_results(self):
        """Search results capped at 10."""
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/search?q=a", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) <= 10


# ── /tenants/{tenancy_id}/dues ─────────────────────────────────────────────

class TestTenantDues:
    def test_invalid_tenancy_returns_404(self):
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r = client.get("/api/v2/app/tenants/999999999/dues", headers=headers)
        assert r.status_code == 404

    def test_no_auth_returns_401(self):
        with TestClient(app) as client:
            r = client.get("/api/v2/app/tenants/1/dues")
        assert r.status_code == 401

    def test_valid_tenancy_returns_200_with_correct_shape(self):
        """
        Finds a real tenancy via the search endpoint, then checks dues shape.
        Skips if the local DB has no active tenancies.
        """
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_make_jwt()}"}
            r_search = client.get("/api/v2/app/tenants/search?q=a", headers=headers)
            assert r_search.status_code == 200
            results = r_search.json()
            if not results:
                pytest.skip("No active tenancies in DB — seed data required for full test")
            tenancy_id = results[0]["tenancy_id"]
            r = client.get(f"/api/v2/app/tenants/{tenancy_id}/dues", headers=headers)

        assert r.status_code == 200
        body = r.json()
        assert "tenancy_id" in body
        assert "tenant_id" in body
        assert "name" in body
        assert "phone" in body
        assert "room_number" in body
        assert "building_code" in body
        assert "rent" in body
        assert "dues" in body
        assert "period_month" in body
        assert isinstance(body["dues"], (int, float))
        assert isinstance(body["tenancy_id"], int)
