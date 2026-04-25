"""Tests for GET /api/v2/app/field-registry endpoint.

Uses FastAPI TestClient + dependency_overrides — no real JWT, no DB,
no network. Zero production data touched.
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.v2.app_router import router
from src.api.v2.auth import AppUser, get_current_user
from src.database.field_registry import fields_for_pwa


# ── TestClient wired with mocked auth ────────────────────────────────────────

def _mock_user():
    return AppUser(user_id="test-uid", phone="9999999999", role="admin", org_id=1)


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = _mock_user

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth():
    return {"Authorization": "Bearer fake-token"}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_field_registry_returns_200():
    r = client.get("/api/v2/app/field-registry", headers=_auth())
    assert r.status_code == 200


def test_field_registry_shape():
    r = client.get("/api/v2/app/field-registry", headers=_auth())
    body = r.json()
    assert "fields" in body
    assert isinstance(body["fields"], list)
    assert len(body["fields"]) > 0


def test_field_registry_count_matches_fields_for_pwa():
    expected = fields_for_pwa()
    r = client.get("/api/v2/app/field-registry", headers=_auth())
    assert len(r.json()["fields"]) == len(expected)


def test_each_field_has_required_keys():
    required = {"key", "display", "source", "db_attr", "type",
                "editable_via_bot", "editable_via_form", "sheet_columns"}
    r = client.get("/api/v2/app/field-registry", headers=_auth())
    for field in r.json()["fields"]:
        missing = required - field.keys()
        assert not missing, f"field {field.get('key')!r} missing keys: {missing}"


def test_no_duplicate_keys():
    r = client.get("/api/v2/app/field-registry", headers=_auth())
    keys = [f["key"] for f in r.json()["fields"]]
    assert len(keys) == len(set(keys)), f"duplicate keys: {[k for k in keys if keys.count(k) > 1]}"


def test_select_fields_have_options():
    r = client.get("/api/v2/app/field-registry", headers=_auth())
    for f in r.json()["fields"]:
        if f["type"] == "select":
            assert f.get("options"), f"select field {f['key']!r} has no options"


def test_health_endpoint_still_works():
    r = client.get("/api/v2/app/health", headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_no_auth_returns_401():
    """Without dependency_overrides, missing token → 401.
    Here we test the raw auth guard directly to confirm it rejects bad tokens.
    """
    from src.api.v2.auth import get_current_user as real_get
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        real_get(authorization=None)
    assert exc_info.value.status_code == 401


def test_bad_bearer_returns_401():
    from src.api.v2.auth import get_current_user as real_get
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        real_get(authorization="Bearer invalid.token.here")
    assert exc_info.value.status_code in (401, 500)
