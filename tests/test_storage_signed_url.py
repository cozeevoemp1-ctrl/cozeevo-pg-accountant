"""
Unit tests for the private-bucket signed-URL helpers in src/services/storage.py
(C-1 fix: Supabase buckets made private, served via short-lived signed URLs).

Covers the pure logic — URL parsing + passthrough safety. The network call
(create_signed_url) is not exercised here; it is verified live in
scripts/_flip_buckets_private.py --verify.
"""
import asyncio

from src.services import storage


def test_split_public_url():
    u = "https://ref.supabase.co/storage/v1/object/public/agreements/2026-08/agreement_x.pdf"
    assert storage._split_bucket_path(u) == ("agreements", "2026-08/agreement_x.pdf")


def test_split_signed_url_drops_token():
    u = "https://ref.supabase.co/storage/v1/object/sign/kyc-documents/onboarding/ab12/selfie.jpg?token=abc.def"
    assert storage._split_bucket_path(u) == ("kyc-documents", "onboarding/ab12/selfie.jpg")


def test_split_non_supabase_returns_none():
    assert storage._split_bucket_path("https://api.getkozzy.com/static/foo.pdf") is None
    assert storage._split_bucket_path("data:image/png;base64,AAAA") is None
    assert storage._split_bucket_path("") is None
    assert storage._split_bucket_path("/media/agreements/x.pdf") is None


def test_sign_stored_url_passthrough_non_supabase():
    # base64 data URLs, local paths, empty, None must be returned unchanged
    for val in ("data:image/png;base64,AAAA", "/static/x.pdf", "", None):
        assert asyncio.run(storage.sign_stored_url(val)) == val


def test_sign_stored_url_fails_open_on_bad_config(monkeypatch):
    # If signing raises (e.g. no service key), return the original value rather
    # than crash the whole API response.
    monkeypatch.setattr(storage, "SUPABASE_SERVICE_KEY", "")
    u = "https://ref.supabase.co/storage/v1/object/public/agreements/2026-08/a.pdf"
    assert asyncio.run(storage.sign_stored_url(u)) == u
