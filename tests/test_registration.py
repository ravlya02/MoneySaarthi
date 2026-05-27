"""Tests for the user registration routes.

POST /register uses the service_role admin API to create users with
email_confirm=True — no email verification required. The Supabase admin
call is mocked so no real credentials are needed.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

_FAKE_SETTINGS = Settings(
    supabase_url="https://example.supabase.co",
    supabase_anon_key="test-anon-key-abc123",
    supabase_service_role_key="test-service-role-key-xyz789",
    supabase_jwt_secret="test-jwt-secret",
    debug=True,
)

_VALID_PAYLOAD = {
    "full_name": "Test User",
    "email": "test@example.com",
    "password": "securepass123",
}


@pytest.fixture()
def client():
    app.dependency_overrides[get_settings] = lambda: _FAKE_SETTINGS
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ── GET /register ────────────────────────────────────────────────────────────

def test_register_page_returns_200(client: TestClient):
    """GET /register renders the registration form with all required fields."""
    resp = client.get("/register")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="full-name"' in body
    assert 'id="email"' in body
    assert 'id="password"' in body
    assert 'id="confirm-password"' in body


def test_register_contains_anon_key(client: TestClient):
    """The anon key must be present in the page so Supabase JS can initialise."""
    resp = client.get("/register")
    assert resp.status_code == 200
    assert _FAKE_SETTINGS.supabase_anon_key in resp.text


def test_register_does_not_expose_secrets(client: TestClient):
    """service_role key and jwt_secret must never appear in rendered HTML."""
    resp = client.get("/register")
    assert resp.status_code == 200
    body = resp.text
    assert _FAKE_SETTINGS.supabase_service_role_key not in body
    assert _FAKE_SETTINGS.supabase_jwt_secret not in body


def test_register_confirm_route_removed(client: TestClient):
    """/register/confirm no longer exists — email verification is disabled."""
    resp = client.get("/register/confirm", follow_redirects=False)
    assert resp.status_code == 404


def test_register_js_uses_server_endpoint_not_supabase_signup(client: TestClient):
    """Page JS must POST to /register (server-side), not call supabase.auth.signUp."""
    resp = client.get("/register")
    assert resp.status_code == 200
    body = resp.text
    assert 'fetch("/register"' in body   # server-side creation
    assert "signInWithPassword" in body  # then sign in
    assert "auth.signUp" not in body     # no client-side signUp


# ── POST /register ───────────────────────────────────────────────────────────

def test_post_register_calls_admin_create_user(client: TestClient):
    """POST /register calls admin.create_user with email_confirm=True."""
    mock_sb = MagicMock()
    with patch("app.routers.auth.service_client", return_value=mock_sb):
        resp = client.post("/register", json=_VALID_PAYLOAD)
    assert resp.status_code == 201
    mock_sb.auth.admin.create_user.assert_called_once_with({
        "email": _VALID_PAYLOAD["email"],
        "password": _VALID_PAYLOAD["password"],
        "email_confirm": True,
        "user_metadata": {"full_name": _VALID_PAYLOAD["full_name"]},
    })


def test_post_register_returns_400_on_supabase_error(client: TestClient):
    """POST /register returns 400 with error detail when Supabase raises."""
    mock_sb = MagicMock()
    mock_sb.auth.admin.create_user.side_effect = Exception("User already registered")
    with patch("app.routers.auth.service_client", return_value=mock_sb):
        resp = client.post("/register", json=_VALID_PAYLOAD)
    assert resp.status_code == 400
    assert "User already registered" in resp.json()["detail"]


def test_post_register_rejects_short_password(client: TestClient):
    """POST /register rejects passwords shorter than 8 characters (Pydantic)."""
    payload = {**_VALID_PAYLOAD, "password": "short"}
    resp = client.post("/register", json=payload)
    assert resp.status_code == 422


def test_post_register_rejects_invalid_email(client: TestClient):
    """POST /register rejects malformed email addresses (Pydantic EmailStr)."""
    payload = {**_VALID_PAYLOAD, "email": "not-an-email"}
    resp = client.post("/register", json=payload)
    assert resp.status_code == 422


def test_post_register_rejects_empty_name(client: TestClient):
    """POST /register rejects blank full_name (Pydantic min_length=1)."""
    payload = {**_VALID_PAYLOAD, "full_name": ""}
    resp = client.post("/register", json=payload)
    assert resp.status_code == 422
