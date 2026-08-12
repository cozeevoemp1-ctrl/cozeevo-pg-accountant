"""
Auth role-source tests — guards the privilege-escalation fix.

Context: `role`/`org_id` must come from the JWT's `app_metadata` claim, never
`user_metadata`. `user_metadata` is self-editable by any authenticated user via
supabase.auth.updateUser(), so trusting it lets anyone grant themselves admin.

These tests also pin down the ROLLOUT behaviour that broke production once:
a token issued BEFORE the account migration has role only in `user_metadata`.
Such a token must resolve to the fail-closed default ("tenant"), NOT silently
inherit admin — and the deploy must therefore force a re-login.

No DB and no network: `_decode_token` is monkeypatched, so these are pure
unit tests of the claim-reading logic.
"""
import pytest

from src.api.v2 import auth as auth_mod


def _user_from(payload, monkeypatch):
    """Run get_current_user against a crafted JWT payload."""
    monkeypatch.setattr(auth_mod, "_decode_token", lambda token: payload)
    return auth_mod.get_current_user(authorization="Bearer fake.token.here")


def test_role_read_from_app_metadata(monkeypatch):
    """The supported shape: role lives in app_metadata (admin-API-only writable)."""
    user = _user_from({
        "sub": "u1",
        "email": "a@b.com",
        "app_metadata": {"role": "admin", "org_id": 1},
        "user_metadata": {"name": "Kiran"},
    }, monkeypatch)
    assert user.role == "admin"
    assert user.org_id == 1
    assert user.name == "Kiran"   # non-privileged display field still from user_metadata


def test_self_set_user_metadata_role_is_ignored(monkeypatch):
    """THE vulnerability: attacker sets user_metadata.role=admin via updateUser().

    app_metadata carries the real (non-admin) role, so admin must NOT be granted.
    """
    user = _user_from({
        "sub": "attacker",
        "app_metadata": {"role": "staff", "org_id": 1},
        "user_metadata": {"role": "admin", "org_id": 99, "name": "evil"},
    }, monkeypatch)
    assert user.role == "staff", "user_metadata.role must never override app_metadata"
    assert user.org_id == 1, "user_metadata.org_id must never override app_metadata"


def test_user_metadata_only_token_fails_closed(monkeypatch):
    """A pre-migration token (role only in user_metadata) must NOT be trusted.

    This is the exact shape that 403'd production during the first rollout.
    Fail-closed is correct; the deploy must force a re-login rather than make
    this case work, because making it work reopens the vulnerability.
    """
    user = _user_from({
        "sub": "u2",
        "user_metadata": {"role": "admin", "org_id": 1, "name": "Kiran"},
    }, monkeypatch)
    assert user.role == "tenant", "must fall back to the least-privileged default"


def test_missing_metadata_fails_closed(monkeypatch):
    user = _user_from({"sub": "u3"}, monkeypatch)
    assert user.role == "tenant"
    assert user.org_id == 1


def test_malformed_org_id_defaults_safely(monkeypatch):
    user = _user_from({
        "sub": "u4",
        "app_metadata": {"role": "admin", "org_id": "not-a-number"},
    }, monkeypatch)
    assert user.org_id == 1


def test_null_metadata_claims_do_not_crash(monkeypatch):
    """Supabase can send explicit nulls; `or {}` must absorb them."""
    user = _user_from({
        "sub": "u5", "app_metadata": None, "user_metadata": None,
    }, monkeypatch)
    assert user.role == "tenant"


def test_missing_bearer_header_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        auth_mod.get_current_user(authorization=None)
    assert e.value.status_code == 401
