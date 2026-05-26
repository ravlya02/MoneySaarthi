"""Tests for auth session and logout routes.

Uses a patched get_settings() so no real Supabase credentials are needed.
The /auth/session endpoint only sets a cookie — no JWT verification required
at that stage (verification happens on protected routes via current_user).
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

_FAKE_SETTINGS = Settings(
    supabase_url="https://example.supabase.co",
    supabase_anon_key="anon-key",
    supabase_service_role_key="service-key",
    supabase_jwt_secret="secret",
    debug=True,  # secure=False so cookies work over plain HTTP in tests
)


@pytest.fixture()
def client():
    app.dependency_overrides[get_settings] = lambda: _FAKE_SETTINGS
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def test_session_sets_cookie(client: TestClient):
    resp = client.post(
        "/auth/session",
        json={"access_token": "tok.abc.123", "refresh_token": "ref.xyz"},
    )
    assert resp.status_code == 204
    cookie = resp.cookies.get("access_token")
    assert cookie == "tok.abc.123"
    # Verify HttpOnly is set in the raw Set-Cookie header
    raw = resp.headers.get("set-cookie", "")
    assert "httponly" in raw.lower()
    assert "samesite=lax" in raw.lower()


def test_logout_clears_cookie(client: TestClient):
    # Plant a cookie first
    client.cookies.set("access_token", "tok.abc.123")
    resp = client.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
    # Cookie should be deleted (max-age=0 or empty value in Set-Cookie)
    raw = resp.headers.get("set-cookie", "")
    assert "access_token" in raw
    cleared = 'access_token=""' in raw or "max-age=0" in raw.lower()
    assert cleared, f"Cookie not cleared. Set-Cookie: {raw}"


def test_login_page_renders(client: TestClient):
    resp = client.get("/login")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="email"' in body
    assert 'id="password"' in body
    assert "anon-key" in body          # anon key present in rendered HTML
    assert "service-key" not in body   # service_role key must never appear
    assert "secret" not in body        # jwt_secret must never appear


def test_root_no_cookie_redirects_to_login(client: TestClient):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]
