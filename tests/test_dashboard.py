"""Tests for the dashboard page (Spec 05).

Covers every item in the Definition of Done:
- Completed report: 200 HTML with chart divs and Plotly JSON payloads
- Tax summary card values and recommended-regime badge
- AI narrative renders / absent
- Action items render / absent
- Goal funding rows
- Pending state with job_id embedded in template context
- Poll JS structure and failed-state banner element
- No poll loop when there is no job
- Unauthenticated redirect to login
- Job status endpoint: 401 JSON (not redirect) without a cookie
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import Settings, get_settings
from app.main import app

# ── Shared test fixtures ─────────────────────────────────────────────────────

_FAKE_SETTINGS = Settings(
    supabase_url="https://example.supabase.co",
    supabase_anon_key="test-anon-key",
    supabase_service_role_key="test-service-role-key",
    supabase_jwt_secret="test-secret",
    debug=True,
)


def _make_token() -> str:
    return jwt.encode(
        {"sub": "user-abc-123", "email": "u@test.com", "aud": "authenticated"},
        _FAKE_SETTINGS.supabase_jwt_secret,
        algorithm="HS256",
    )


@pytest.fixture()
def client():
    """Unauthenticated TestClient."""
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


# ── Sample DB rows ───────────────────────────────────────────────────────────

_REPORT = {
    "generated_at": "2025-12-01T10:00:00",
    "assessment_year": "AY 2026-27",
    "old_regime_tax": "150000",
    "new_regime_tax": "120000",
    "recommended_regime": "New",
    "breakdown": {},
    "ai_narrative": "Your financial health is strong. Consider rebalancing towards debt.",
    "ai_action_items": [
        {
            "action": "Invest in ELSS funds",
            "instrument": "ELSS",
            "rationale": "Save up to ₹1.5L under Section 80C.",
            "source": None,
        }
    ],
}

_REPORT_NO_AI = {
    **_REPORT,
    "ai_narrative": None,
    "ai_action_items": [],
}

_PLAN = {
    "target_equity_pct": "60",
    "target_debt_pct": "25",
    "target_realestate_pct": "10",
    "target_metals_pct": "5",
    "plan_detail": {
        "goal_funding": [
            {
                "goal_name": "Retirement",
                "status": "on-track",
                "future_value_required": "50000000",
                "suggested_monthly_sip": "25000",
            }
        ]
    },
}

_JOB = {"id": "job-abc-123", "status": "running"}


# ── Mock helper ──────────────────────────────────────────────────────────────

def _make_db_mock(**table_data):
    """Return a mock anon DB client.

    ``table_data`` maps table_name → list-of-rows.  Each table mock supports
    the two chain patterns used in dashboard.py:
      - .select().eq().order().limit().execute()   (list queries)
      - .select().eq().eq().single().execute()      (job_status query)
    """
    db = MagicMock()

    def table_side_effect(name):
        rows = table_data.get(name, [])
        t = MagicMock()
        # List-query chain
        t.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = rows
        # Single-row chain (job_status: .eq().eq().single())
        t.select.return_value.eq.return_value.eq.return_value \
            .single.return_value.execute.return_value.data = (
                rows[0] if rows else None
            )
        return t

    db.table.side_effect = table_side_effect
    return db


# ── Completed-report tests ───────────────────────────────────────────────────

def test_dashboard_completed_report_200(auth_client):
    """GET /dashboard with a completed report returns 200 HTML with chart divs
    and both alloc_fig / tax_fig JSON payloads embedded in the page scripts."""
    db = _make_db_mock(
        tax_reports=[_REPORT],
        investment_plans=[_PLAN],
    )
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert 'id="allocChart"' in resp.text
    assert 'id="taxChart"' in resp.text
    # Plotly JSON blobs are embedded via alloc_fig / tax_fig | safe
    assert "Plotly.newPlot" in resp.text
    assert "alloc" in resp.text
    assert "taxChart" in resp.text


def test_tax_summary_card_values(auth_client):
    """Tax summary card shows old/new regime amounts and the regime badge."""
    db = _make_db_mock(tax_reports=[_REPORT], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    # ₹150,000 and ₹120,000 formatted
    assert "150,000" in resp.text
    assert "120,000" in resp.text
    # Recommended regime badge
    assert "New Regime Recommended" in resp.text


def test_tax_summary_card_old_regime_badge(auth_client):
    """When old regime is recommended the amber badge is shown."""
    report = {**_REPORT, "recommended_regime": "Old"}
    db = _make_db_mock(tax_reports=[report], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "Old Regime Recommended" in resp.text
    assert "badge-amber" in resp.text


def test_ai_narrative_renders_when_present(auth_client):
    """AI narrative prose block is present when ai_narrative is not None."""
    db = _make_db_mock(tax_reports=[_REPORT], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert _REPORT["ai_narrative"] in resp.text


def test_ai_narrative_absent_when_none(auth_client):
    """AI narrative section is not rendered (not just empty) when ai_narrative is None."""
    db = _make_db_mock(tax_reports=[_REPORT_NO_AI], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "AI Analysis" not in resp.text


def test_action_items_render_when_present(auth_client):
    """Action items section renders with action, instrument, and rationale."""
    db = _make_db_mock(tax_reports=[_REPORT], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "Action Items" in resp.text
    assert "Invest in ELSS funds" in resp.text
    assert "ELSS" in resp.text
    assert "Save up to" in resp.text


def test_action_items_absent_when_empty(auth_client):
    """Action items section is absent (not present as empty block) when list is empty."""
    db = _make_db_mock(tax_reports=[_REPORT_NO_AI], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "Action Items" not in resp.text


def test_goal_funding_rows_render(auth_client):
    """Goal funding rows appear with goal name, status badge, and SIP amount."""
    db = _make_db_mock(tax_reports=[_REPORT], investment_plans=[_PLAN])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "Retirement" in resp.text
    assert "on-track" in resp.text
    assert "25,000" in resp.text   # SIP formatted


def test_goal_funding_absent_when_no_plan(auth_client):
    """Goal funding section is absent when there is no investment_plans row."""
    db = _make_db_mock(tax_reports=[_REPORT], investment_plans=[])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "Goal Funding" not in resp.text


# ── Pending-state tests ──────────────────────────────────────────────────────

def test_pending_with_queued_job_embeds_job_id(auth_client):
    """No report + a queued job → pending page with job_id in the template context."""
    db = _make_db_mock(
        tax_reports=[],
        report_jobs=[_JOB],
    )
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    # job_id must be embedded in the rendered script (not only available via URL)
    assert "job-abc-123" in resp.text


def test_pending_poll_js_calls_status_endpoint(auth_client):
    """Poll JS references /jobs/${jobId}/status."""
    db = _make_db_mock(tax_reports=[], report_jobs=[_JOB])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert "/jobs/${jobId}/status" in resp.text


def test_pending_poll_js_redirects_on_complete(auth_client):
    """Poll JS redirects to /dashboard on status === 'complete'."""
    db = _make_db_mock(tax_reports=[], report_jobs=[_JOB])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert "location.href = '/dashboard'" in resp.text


def test_pending_failed_state_ui(auth_client):
    """Pending page contains the error-banner div for the failed state."""
    db = _make_db_mock(tax_reports=[], report_jobs=[_JOB])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    assert 'id="error-banner"' in resp.text
    # JS sets banner text from error_detail
    assert "error_detail" in resp.text


def test_pending_no_job_no_poll_loop(auth_client):
    """No report and no job → pending page with empty jobId in the script.

    The template renders job_id as "" so `const jobId = "" || ...`.  The poll
    function checks `if (!jobId) return;` which exits immediately when jobId is
    falsy (no URL param either), so no poll loop fires.
    """
    db = _make_db_mock(tax_reports=[], report_jobs=[])
    with patch("app.routers.dashboard.anon_client", return_value=db):
        resp = auth_client.get("/dashboard")

    assert resp.status_code == 200
    # Template variable is empty → jobId renders as ""
    assert 'const jobId = "" ||' in resp.text


# ── Auth / redirect tests ────────────────────────────────────────────────────

def test_dashboard_no_auth_cookie_redirects(client):
    """GET /dashboard without an auth cookie → 302 to /login?next=/dashboard."""
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?next=/dashboard"


def test_job_status_no_cookie_returns_401_json(client):
    """GET /jobs/<id>/status without a cookie → 401 JSON (not a redirect)."""
    resp = client.get("/jobs/fake-id/status", follow_redirects=False)
    assert resp.status_code == 401
    data = resp.json()
    assert "detail" in data
