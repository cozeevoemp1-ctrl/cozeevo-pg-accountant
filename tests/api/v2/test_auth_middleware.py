import os, time, jwt, pytest
from fastapi.testclient import TestClient

TEST_SECRET = "test-secret-abcdefghijklmnopqrstuvwxyz1234"
os.environ["SUPABASE_JWT_SECRET"] = TEST_SECRET

from main import app

client = TestClient(app)

def _make_jwt(role="admin", org_id=1, phone="+917845952289"):
    return jwt.encode(
        {
            "sub": "user-uuid-123",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "phone": phone,
            "user_metadata": {"role": role, "org_id": org_id},
        },
        TEST_SECRET,
        algorithm="HS256",
    )

def test_app_endpoint_requires_jwt():
    r = client.get("/api/v2/app/health")
    assert r.status_code == 401

def test_app_endpoint_accepts_valid_jwt():
    r = client.get("/api/v2/app/health", headers={"Authorization": f"Bearer {_make_jwt()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["user_id"] == "user-uuid-123"
    assert body["role"] == "admin"

def test_app_endpoint_rejects_invalid_jwt():
    r = client.get("/api/v2/app/health", headers={"Authorization": "Bearer invalid.token.here"})
    assert r.status_code == 401

def test_app_endpoint_rejects_expired_jwt():
    expired = jwt.encode(
        {"sub": "u", "aud": "authenticated", "exp": int(time.time()) - 60},
        TEST_SECRET, algorithm="HS256",
    )
    r = client.get("/api/v2/app/health", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401

def test_app_endpoint_rejects_wrong_audience():
    wrong = jwt.encode(
        {"sub": "u", "aud": "not-authenticated", "exp": int(time.time()) + 60},
        TEST_SECRET, algorithm="HS256",
    )
    r = client.get("/api/v2/app/health", headers={"Authorization": f"Bearer {wrong}"})
    assert r.status_code == 401
