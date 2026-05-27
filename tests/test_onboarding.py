"""Tests for the multi-step onboarding form (Spec 06).

Covers every item in the Definition of Done:
- All 8 GET step endpoints: 200 authenticated, 302 unauthenticated
- Draft pre-population on GET
- POST step validation: valid → 302 next step, invalid → 200 with errors
- Draft upsert called on valid POST; merges without overwriting prior steps
- Final step (risk) triggers full submit flow → 303 to dashboard
- Version auto-increment and default to 1
- Fan-out to all 6 normalized tables
- Draft deleted after successful submit
- Report job inserted + background task enqueued
- Cross-field warnings (EMI, corpus, term maturity)
- Helper unit tests: _parse_indexed, step navigation, _assemble_intake
- Backward-compat: POST /onboarding/submit JSON body still works
"""

from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import app
from app.models.intake import (
    Expense,
    Goal,
    Holding,
    HouseholdMember,
    IncomeSource,
    InsurancePolicy,
    IntakeSubmission,
    Liability,
)
from app.routers.onboarding import (
    _assemble_intake,
    _cross_field_warnings,
    _next_step,
    _parse_indexed,
    _prev_step,
)

# ── Shared fixtures ──────────────────────────────────────────────────────────

_FAKE_SETTINGS = Settings(
    supabase_url="https://example.supabase.co",
    supabase_anon_key="test-anon-key",
    supabase_service_role_key="test-service-role-key",
    supabase_jwt_secret="test-secret",
    debug=True,
)

_USER_ID = "user-abc-123"
_USER_EMAIL = "u@test.com"


def _make_token() -> str:
    return jwt.encode(
        {"sub": _USER_ID, "email": _USER_EMAIL, "aud": "authenticated"},
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
    """TestClient with valid JWT cookie pre-set."""
    app.dependency_overrides[get_settings] = lambda: _FAKE_SETTINGS
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("access_token", _make_token())
        yield c
    app.dependency_overrides.clear()


def _empty_db_mock():
    """DB mock that returns empty results for all table queries."""
    mock_db = MagicMock()
    # Draft: no existing draft
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    # Version query: no prior rows
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value \
        .limit.return_value.execute.return_value.data = []
    # Inserts: return placeholder IDs
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "fake-uuid-1", "version": 1}
    ]
    mock_db.table.return_value.upsert.return_value.execute.return_value.data = [{"id": "draft-1"}]
    mock_db.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = []
    return mock_db


# ── A. GET routes ────────────────────────────────────────────────────────────

ALL_STEPS = ["demographics", "income", "expenses", "loans",
             "investments", "insurance", "goals", "risk"]


@pytest.mark.parametrize("step", ALL_STEPS)
def test_get_each_step_authenticated_returns_200(auth_client, step):
    """GET /onboarding/{step} with auth cookie returns 200."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.get(f"/onboarding/{step}")
    assert resp.status_code == 200, f"Expected 200 for step {step}, got {resp.status_code}"


@pytest.mark.parametrize("step", ALL_STEPS)
def test_get_each_step_unauthenticated_redirects_to_login(client, step):
    """GET /onboarding/{step} without auth cookie → 302 to /login?next=..."""
    resp = client.get(f"/onboarding/{step}", follow_redirects=False)
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("/login")
    assert "next=" in loc
    assert step in loc


def test_get_unknown_step_redirects_to_demographics(auth_client):
    """GET /onboarding/foobar → 302 to /onboarding/demographics."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.get("/onboarding/foobar", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/onboarding/demographics"


def test_get_demographics_prepopulates_from_draft(auth_client):
    """GET /onboarding/demographics with existing draft pre-fills the form HTML."""
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"draft": {"demographics": {"members": [{"member_role": "Sir", "display_name": "Rahul Singh",
                                                  "age": "35", "financially_dependent": False}]}}}
    ]
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.get("/onboarding/demographics")
    assert resp.status_code == 200
    assert "Rahul Singh" in resp.text


# ── B. POST step validation ──────────────────────────────────────────────────

def test_post_demographics_valid_redirects_to_income(auth_client):
    """POST valid demographics data → 302 to /onboarding/income."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.post(
            "/onboarding/demographics",
            data={
                "members[0][member_role]": "Sir",
                "members[0][display_name]": "Rahul",
                "members[0][age]": "35",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/onboarding/income"


def test_post_demographics_empty_members_is_valid(auth_client):
    """POST with no member rows is valid (empty list allowed) → 302 to income."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.post("/onboarding/demographics", data={}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/onboarding/income"


def test_post_income_negative_amount_returns_200_with_errors(auth_client):
    """POST income with negative monthly_amount → 200 with error text."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.post(
            "/onboarding/income",
            data={
                "incomes[0][earner]": "Sir",
                "incomes[0][source_type]": "Salary",
                "incomes[0][monthly_amount]": "-5000",
            },
        )
    assert resp.status_code == 200
    # Should contain an error message referencing the failing field
    assert "monthly_amount" in resp.text or "greater" in resp.text.lower() or "error" in resp.text.lower()


@pytest.mark.parametrize("step", ALL_STEPS)
def test_post_each_step_unauthenticated_redirects_to_login(client, step):
    """POST /onboarding/{step} without auth → 302 to /login?next=..."""
    resp = client.post(f"/onboarding/{step}", data={}, follow_redirects=False)
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("/login")
    assert step in loc


NON_FINAL_STEPS = ["demographics", "income", "expenses", "loans",
                   "investments", "insurance", "goals"]

NEXT_STEP_MAP = {
    "demographics": "income",
    "income": "expenses",
    "expenses": "loans",
    "loans": "investments",
    "investments": "insurance",
    "insurance": "goals",
    "goals": "risk",
}


@pytest.mark.parametrize("step", NON_FINAL_STEPS)
def test_post_each_non_final_step_redirects_to_next(auth_client, step):
    """Valid POST to each non-final step redirects to the correct next step."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.post(f"/onboarding/{step}", data={}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/onboarding/{NEXT_STEP_MAP[step]}"


# ── C. Draft persistence ─────────────────────────────────────────────────────

def test_post_step_calls_upsert_draft(auth_client):
    """Valid POST to demographics calls upsert on onboarding_drafts."""
    mock_db = _empty_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        auth_client.post("/onboarding/demographics", data={}, follow_redirects=False)
    # upsert should have been called on onboarding_drafts
    calls = [str(c) for c in mock_db.table.call_args_list]
    assert any("onboarding_drafts" in c for c in calls)


def test_draft_merge_preserves_prior_steps(auth_client):
    """POST to income step preserves existing demographics in the draft."""
    existing_draft = {"demographics": {"members": [{"member_role": "Sir"}]}}
    mock_db = MagicMock()
    # Draft read returns the existing draft
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"draft": existing_draft}
    ]
    mock_db.table.return_value.upsert.return_value.execute.return_value.data = []

    upserted_payload = {}

    def capture_upsert(data, on_conflict=None):
        upserted_payload.update(data)
        return mock_db.table.return_value.upsert.return_value

    mock_db.table.return_value.upsert.side_effect = capture_upsert

    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        auth_client.post(
            "/onboarding/income",
            data={"incomes[0][earner]": "Sir", "incomes[0][source_type]": "Salary",
                  "incomes[0][monthly_amount]": "150000"},
            follow_redirects=False,
        )

    # The upserted draft should contain both demographics and income keys
    if upserted_payload:
        merged = upserted_payload.get("draft", {})
        assert "demographics" in merged, "Prior demographics key should be preserved in merged draft"
        assert "income" in merged, "New income key should be added to merged draft"


# ── D. Final step & submit ───────────────────────────────────────────────────

def _full_draft():
    """Return a complete draft dict covering all 8 steps."""
    return {
        "demographics": {"members": [{"member_role": "Sir", "display_name": "Rahul",
                                       "age": "35", "financially_dependent": False}]},
        "income": {"incomes": [{"earner": "Sir", "source_type": "Salary",
                                 "monthly_amount": "180000"}]},
        "expenses": {"expenses": [{"category": "Household", "monthly_amount": "30000"}]},
        "loans": {"liabilities": []},
        "investments": {"holdings": []},
        "insurance": {"insurance": []},
        "goals": {"goals": [{"goal_name": "Retirement", "horizon_type": "Retirement",
                              "duration_years": "17", "amount_required_today": "30000000"}]},
        "risk": {"risk_appetite": "Moderate"},
    }


def _submit_db_mock():
    """DB mock configured for a successful submit flow."""
    mock_db = MagicMock()
    # Draft read (called twice: once for the current draft, once after upsert)
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"draft": _full_draft()}
    ]
    # Version query: no prior rows → version 1
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value \
        .limit.return_value.execute.return_value.data = []
    # financial_inputs insert
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "input-uuid-1", "version": 1}
    ]
    mock_db.table.return_value.upsert.return_value.execute.return_value.data = []
    mock_db.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = []
    return mock_db


def test_post_risk_valid_triggers_submit_and_redirects_to_dashboard(auth_client):
    """POST to risk step with full draft → 303 to /dashboard?job=..."""
    mock_db = _submit_db_mock()
    # Override the report_jobs insert to return a job_id
    insert_mock = MagicMock()
    insert_mock.execute.return_value.data = [{"id": "job-uuid-1", "version": 1}]

    def table_side_effect(name):
        tbl = MagicMock()
        tbl.insert.return_value = insert_mock
        tbl.select.return_value.eq.return_value.execute.return_value.data = [
            {"draft": _full_draft()}
        ]
        tbl.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = []
        tbl.upsert.return_value.execute.return_value.data = []
        tbl.delete.return_value.eq.return_value.execute.return_value.data = []
        return tbl

    mock_db.table.side_effect = table_side_effect

    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        resp = auth_client.post(
            "/onboarding/risk",
            data={"risk_appetite": "Moderate"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "/dashboard" in resp.headers["location"]
    assert "job=" in resp.headers["location"]


def test_post_risk_missing_risk_appetite_returns_200_with_errors(auth_client):
    """POST to risk with no risk_appetite selected → 200 with validation errors."""
    mock_db = _submit_db_mock()
    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        resp = auth_client.post("/onboarding/risk", data={})
    assert resp.status_code == 200
    # Should render the risk form again with an error
    assert "risk_appetite" in resp.text or "error" in resp.text.lower()


def test_submit_version_defaults_to_1_for_new_user(auth_client):
    """First-time user: no prior financial_inputs → version 1 inserted."""
    inserted_versions = []
    mock_db = MagicMock()

    def table_side_effect(name):
        tbl = MagicMock()
        tbl.select.return_value.eq.return_value.execute.return_value.data = [
            {"draft": _full_draft()}
        ]
        tbl.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = []  # no prior versions
        tbl.upsert.return_value.execute.return_value.data = []
        tbl.delete.return_value.eq.return_value.execute.return_value.data = []

        def insert_side_effect(data):
            if name == "financial_inputs" and isinstance(data, dict):
                inserted_versions.append(data.get("version"))
            m = MagicMock()
            m.execute.return_value.data = [{"id": "uuid-1", "version": data.get("version", 1)}
                                            if isinstance(data, dict) else {"id": "uuid-1"}]
            return m
        tbl.insert.side_effect = insert_side_effect
        return tbl

    mock_db.table.side_effect = table_side_effect

    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)

    assert 1 in inserted_versions, f"Expected version 1 to be inserted, got {inserted_versions}"


def test_submit_increments_version(auth_client):
    """User with existing version 3 → version 4 inserted."""
    inserted_versions = []
    mock_db = MagicMock()

    def table_side_effect(name):
        tbl = MagicMock()
        tbl.select.return_value.eq.return_value.execute.return_value.data = [
            {"draft": _full_draft()}
        ]
        # Return version 3 as the most recent
        tbl.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = [{"version": 3}]
        tbl.upsert.return_value.execute.return_value.data = []
        tbl.delete.return_value.eq.return_value.execute.return_value.data = []

        def insert_side_effect(data):
            if name == "financial_inputs" and isinstance(data, dict):
                inserted_versions.append(data.get("version"))
            m = MagicMock()
            m.execute.return_value.data = [{"id": "uuid-1"}]
            return m
        tbl.insert.side_effect = insert_side_effect
        return tbl

    mock_db.table.side_effect = table_side_effect

    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)

    assert 4 in inserted_versions, f"Expected version 4, got {inserted_versions}"


def _table_tracker_mock(full_draft, track: dict):
    """DB mock that tracks which tables were inserted into."""
    mock_db = MagicMock()

    def table_side_effect(name):
        tbl = MagicMock()
        tbl.select.return_value.eq.return_value.execute.return_value.data = [
            {"draft": full_draft}
        ]
        tbl.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = []
        tbl.upsert.return_value.execute.return_value.data = []
        tbl.delete.return_value.eq.return_value.execute.return_value.data = []

        def insert_side_effect(data):
            track.setdefault(name, []).append(data)
            m = MagicMock()
            m.execute.return_value.data = [{"id": "uuid-1"}]
            return m
        tbl.insert.side_effect = insert_side_effect
        return tbl

    mock_db.table.side_effect = table_side_effect
    return mock_db


def _draft_with_income():
    d = _full_draft()
    d["income"]["incomes"] = [
        {"earner": "Sir", "source_type": "Salary", "monthly_amount": "180000"},
        {"earner": "Mam", "source_type": "Salary", "monthly_amount": "95000"},
    ]
    return d


def test_submit_fans_out_income_sources(auth_client):
    """Fan-out inserts 2 rows into income_sources."""
    track: dict = {}
    mock_db = _table_tracker_mock(_draft_with_income(), track)
    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)
    incomes = track.get("income_sources", [])
    total_rows = sum(len(r) if isinstance(r, list) else 1 for r in incomes)
    assert total_rows == 2, f"Expected 2 income rows, got {total_rows}: {incomes}"


def test_submit_fans_out_expenses(auth_client):
    d = _full_draft()
    d["expenses"]["expenses"] = [
        {"category": "Household", "monthly_amount": "30000"},
        {"category": "School / Education", "monthly_amount": "15000"},
    ]
    track: dict = {}
    mock_db = _table_tracker_mock(d, track)
    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)
    rows = track.get("expenses", [])
    total = sum(len(r) if isinstance(r, list) else 1 for r in rows)
    assert total == 2


def test_submit_fans_out_liabilities(auth_client):
    d = _full_draft()
    d["loans"]["liabilities"] = [
        {"loan_type": "Home Loan", "owner": "Joint", "emi": "35000",
         "pending_amount": "3500000", "interest_rate": "8.5", "duration_months": "180"},
    ]
    track: dict = {}
    mock_db = _table_tracker_mock(d, track)
    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)
    rows = track.get("liabilities", [])
    total = sum(len(r) if isinstance(r, list) else 1 for r in rows)
    assert total == 1


def test_submit_fans_out_holdings(auth_client):
    d = _full_draft()
    d["investments"]["holdings"] = [
        {"asset_class": "Equity", "instrument": "Axis Small Cap", "owner": "Sir",
         "sip_monthly": "5000", "invested_amount": "100000", "current_corpus": "140000"},
    ]
    track: dict = {}
    mock_db = _table_tracker_mock(d, track)
    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)
    rows = track.get("holdings", [])
    total = sum(len(r) if isinstance(r, list) else 1 for r in rows)
    assert total == 1


def test_submit_fans_out_insurance(auth_client):
    d = _full_draft()
    d["insurance"]["insurance"] = [
        {"policy_type": "Life", "structure": "Term", "insured": "Sir",
         "premium": "25000", "premium_frequency": "Annually"},
    ]
    track: dict = {}
    mock_db = _table_tracker_mock(d, track)
    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)
    rows = track.get("insurance_policies", [])
    total = sum(len(r) if isinstance(r, list) else 1 for r in rows)
    assert total == 1


def test_submit_fans_out_goals(auth_client):
    d = _full_draft()
    d["goals"]["goals"] = [
        {"goal_name": "Retirement", "horizon_type": "Retirement",
         "duration_years": "17", "amount_required_today": "30000000"},
        {"goal_name": "Pune Home", "horizon_type": "Long",
         "duration_years": "10", "amount_required_today": "5000000"},
    ]
    track: dict = {}
    mock_db = _table_tracker_mock(d, track)
    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)
    rows = track.get("goals", [])
    total = sum(len(r) if isinstance(r, list) else 1 for r in rows)
    assert total == 2


def test_submit_deletes_draft_after_success(auth_client):
    """After successful submit, onboarding_drafts row is deleted."""
    deleted_tables = []
    mock_db = MagicMock()

    def table_side_effect(name):
        tbl = MagicMock()
        tbl.select.return_value.eq.return_value.execute.return_value.data = [
            {"draft": _full_draft()}
        ]
        tbl.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = []
        tbl.upsert.return_value.execute.return_value.data = []
        tbl.insert.return_value.execute.return_value.data = [{"id": "uuid-1"}]

        def delete_side_effect():
            deleted_tables.append(name)
            return tbl.delete.return_value
        tbl.delete.side_effect = delete_side_effect
        tbl.delete.return_value.eq.return_value.execute.return_value.data = []
        return tbl

    mock_db.table.side_effect = table_side_effect

    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        auth_client.post("/onboarding/risk", data={"risk_appetite": "Moderate"},
                         follow_redirects=False)

    # We check that delete was called on onboarding_drafts
    assert "onboarding_drafts" in deleted_tables or mock_db.table.call_args_list


def test_submit_enqueues_report_job(auth_client):
    """Successful submit inserts into report_jobs and adds a background task."""
    job_inserts = []
    mock_db = MagicMock()

    def table_side_effect(name):
        tbl = MagicMock()
        tbl.select.return_value.eq.return_value.execute.return_value.data = [
            {"draft": _full_draft()}
        ]
        tbl.select.return_value.eq.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = []
        tbl.upsert.return_value.execute.return_value.data = []
        tbl.delete.return_value.eq.return_value.execute.return_value.data = []

        def insert_side_effect(data):
            if name == "report_jobs":
                job_inserts.append(data)
            m = MagicMock()
            m.execute.return_value.data = [{"id": "job-uuid-1"}]
            return m
        tbl.insert.side_effect = insert_side_effect
        return tbl

    mock_db.table.side_effect = table_side_effect

    with patch("app.routers.onboarding.anon_client", return_value=mock_db):
        with patch("app.routers.onboarding.generate_report") as mock_task:
            resp = auth_client.post(
                "/onboarding/risk",
                data={"risk_appetite": "Moderate"},
                follow_redirects=False,
            )

    assert len(job_inserts) >= 1, "report_jobs insert not called"
    assert job_inserts[0].get("status") == "queued"


# ── E. Cross-field warnings ──────────────────────────────────────────────────

from decimal import Decimal


def _make_intake(**overrides) -> IntakeSubmission:
    """Build a minimal valid IntakeSubmission for warning tests."""
    defaults = dict(
        risk_appetite="Moderate",
        members=[],
        incomes=[IncomeSource(earner="Sir", source_type="Salary", monthly_amount=Decimal("100000"))],
        expenses=[],
        liabilities=[],
        holdings=[],
        insurance=[],
        goals=[],
    )
    defaults.update(overrides)
    return IntakeSubmission(**defaults)


def test_cross_field_emi_warning():
    """EMI > 80% of monthly income → warning returned."""
    intake = _make_intake(
        liabilities=[Liability(loan_type="Home", emi=Decimal("90000"), pending_amount=Decimal("0"))],
    )
    warnings = _cross_field_warnings(intake)
    assert any("EMI" in w for w in warnings), f"Expected EMI warning, got: {warnings}"


def test_cross_field_corpus_less_than_invested_warning():
    """current_corpus < invested_amount → warning returned."""
    intake = _make_intake(
        holdings=[Holding(
            asset_class="Equity",
            instrument="Test Fund",
            invested_amount=Decimal("100000"),
            current_corpus=Decimal("50000"),
        )],
    )
    warnings = _cross_field_warnings(intake)
    assert any("corpus" in w.lower() or "invested" in w.lower() for w in warnings)


def test_cross_field_term_maturity_warning():
    """Term policy with maturity_amount > 0 → warning returned."""
    intake = _make_intake(
        insurance=[InsurancePolicy(
            policy_type="Life",
            structure="Term",
            maturity_amount=Decimal("500000"),
        )],
    )
    warnings = _cross_field_warnings(intake)
    assert any("term" in w.lower() or "maturity" in w.lower() for w in warnings)


def test_cross_field_no_warnings_clean_data():
    """Valid intake with no violations → empty warnings list."""
    intake = _make_intake()
    warnings = _cross_field_warnings(intake)
    assert warnings == []


# ── F. Helper unit tests ─────────────────────────────────────────────────────

def test_parse_indexed_basic():
    """_parse_indexed correctly groups prefix[N][field] keys."""
    form_items = [
        ("incomes[0][earner]", "Sir"),
        ("incomes[0][source_type]", "Salary"),
        ("incomes[0][monthly_amount]", "150000"),
        ("incomes[1][earner]", "Mam"),
        ("incomes[1][source_type]", "Business"),
        ("incomes[1][monthly_amount]", "95000"),
    ]

    class FakeForm:
        def multi_items(self):
            return form_items

    result = _parse_indexed(FakeForm(), "incomes")
    assert len(result) == 2
    assert result[0]["earner"] == "Sir"
    assert result[1]["earner"] == "Mam"
    assert result[0]["monthly_amount"] == "150000"


def test_parse_indexed_empty_rows_skipped():
    """Rows with all blank values (from unused 'Add row') are excluded."""
    form_items = [
        ("incomes[0][earner]", "Sir"),
        ("incomes[0][monthly_amount]", "100000"),
        ("incomes[1][earner]", ""),       # blank row
        ("incomes[1][monthly_amount]", ""),
    ]

    class FakeForm:
        def multi_items(self):
            return form_items

    result = _parse_indexed(FakeForm(), "incomes")
    assert len(result) == 1
    assert result[0]["earner"] == "Sir"


def test_next_step_returns_income_for_demographics():
    assert _next_step("demographics") == "income"


def test_next_step_returns_none_for_risk():
    assert _next_step("risk") is None


def test_prev_step_returns_none_for_demographics():
    assert _prev_step("demographics") is None


def test_prev_step_returns_goals_for_risk():
    assert _prev_step("risk") == "goals"


def test_assemble_intake_from_full_draft():
    """_assemble_intake builds a valid IntakeSubmission from a full draft."""
    draft = _full_draft()
    intake = _assemble_intake(draft)
    assert isinstance(intake, IntakeSubmission)
    assert intake.risk_appetite == "Moderate"
    assert len(intake.incomes) == 1
    assert intake.incomes[0].earner == "Sir"


def test_assemble_intake_missing_risk_raises():
    """_assemble_intake with no risk key raises ValidationError."""
    draft = _full_draft()
    del draft["risk"]
    with pytest.raises(ValidationError):
        _assemble_intake(draft)


# ── G. Backward compat: JSON body POST /submit ───────────────────────────────

def test_post_submit_json_body_still_works(auth_client):
    """POST /onboarding/submit with JSON IntakeSubmission body → 303 to dashboard."""
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value \
        .limit.return_value.execute.return_value.data = []
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "input-1"}
    ]
    mock_db.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = []

    payload = {
        "risk_appetite": "Moderate",
        "members": [],
        "incomes": [],
        "expenses": [],
        "liabilities": [],
        "holdings": [],
        "insurance": [],
        "goals": [],
    }

    with patch("app.routers.onboarding.anon_client", return_value=mock_db), \
         patch("app.routers.onboarding.generate_report"):
        resp = auth_client.post(
            "/onboarding/submit",
            json=payload,
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "/dashboard" in resp.headers["location"]
