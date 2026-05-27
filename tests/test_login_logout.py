"""Tests for login/logout redirect logic and authenticated nav rendering.

Uses a patched get_settings() with a known jwt_secret so tests can mint valid
tokens without a real Supabase project.
"""

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import Settings, get_settings
from app.main import app

_FAKE_SETTINGS = Settings(
    supabase_url="https://example.supabase.co",
    supabase_anon_key="test-anon-key",
    supabase_service_role_key="test-service-role-key",
    supabase_jwt_secret="test-secret",
    debug=True,
)


def _make_token() -> str:
    """Mint a minimal Supabase-style JWT signed with the fake secret."""
    return jwt.encode(
        {"sub": "user-abc-123", "email": "u@test.com", "aud": "authenticated"},
        _FAKE_SETTINGS.supabase_jwt_secret,
        algorithm="HS256",
    )


@pytest.fixture()
def client():
    app.dependency_overrides[get_settings] = lambda: _FAKE_SETTINGS
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client():
    """TestClient with a valid JWT cookie pre-set."""
    app.dependency_overrides[get_settings] = lambda: _FAKE_SETTINGS
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("access_token", _make_token())
        yield c
    app.dependency_overrides.clear()


# ── Unauthenticated redirects ────────────────────────────────────────────────

def test_dashboard_no_cookie_redirects_to_login(client: TestClient):
    """/dashboard without a session cookie redirects to /login?next=/dashboard."""
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?next=/dashboard"


def test_onboarding_no_cookie_redirects_to_login(client: TestClient):
    """/onboarding/demographics without a cookie redirects to /login?next=..."""
    resp = client.get("/onboarding/demographics", follow_redirects=False)
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("/login")
    assert "next=" in loc
    assert "demographics" in loc


# ── Already-authenticated redirects ─────────────────────────────────────────

def test_login_with_valid_cookie_redirects_to_dashboard(auth_client: TestClient):
    """/login with a valid session cookie redirects to /dashboard."""
    resp = auth_client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


def test_register_with_valid_cookie_redirects_to_dashboard(auth_client: TestClient):
    """/register with a valid session cookie redirects to /dashboard."""
    resp = auth_client.get("/register", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


# ── Logout banner ────────────────────────────────────────────────────────────

def test_logout_appends_logged_out_param(client: TestClient):
    """POST /auth/logout redirects to /login?logged_out=1."""
    resp = client.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "logged_out=1" in resp.headers["location"]


def test_login_page_shows_banner_when_logged_out(client: TestClient):
    """GET /login?logged_out=1 renders the 'You have been signed out.' notice."""
    resp = client.get("/login?logged_out=1")
    assert resp.status_code == 200
    assert "You have been signed out." in resp.text


# ── ?next= redirect ──────────────────────────────────────────────────────────

def test_next_param_embedded_in_login_page(client: TestClient):
    """/login?next=/onboarding/demographics embeds next_url in the page."""
    resp = client.get("/login?next=/onboarding/demographics")
    assert resp.status_code == 200
    assert "/onboarding/demographics" in resp.text


def test_open_redirect_rejected(client: TestClient):
    """next=//evil.com must be sanitised to /dashboard (open-redirect guard)."""
    resp = client.get("/login?next=//evil.com")
    assert resp.status_code == 200
    # next_url must be /dashboard, not //evil.com
    assert "//evil.com" not in resp.text
    assert "/dashboard" in resp.text


# ── JSON endpoint keeps 401 ──────────────────────────────────────────────────

def test_job_status_no_cookie_returns_401(client: TestClient):
    """/jobs/{id}/status without a cookie returns 401 JSON, not a redirect."""
    resp = client.get("/jobs/fake-id/status", follow_redirects=False)
    assert resp.status_code == 401
    # Must be JSON, not a redirect
    data = resp.json()
    assert "detail" in data


# ── Nav bar renders for authenticated users ──────────────────────────────────

def test_authenticated_dashboard_shows_nav(auth_client: TestClient):
    """GET /dashboard with a valid cookie renders the site nav (Sign out button)."""
    # Mock the Supabase DB call so it returns no report (renders pending page).
    from unittest.mock import MagicMock, patch

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value \
        .data = []

    with patch("app.routers.dashboard.anon_client", return_value=mock_db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert '<nav class="site-nav">' in resp.text
