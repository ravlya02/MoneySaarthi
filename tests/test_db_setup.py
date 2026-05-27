"""Tests for Step 02 — Create Database Setup.

Covered:
  1. apply.py --dry-run exits 0 and prints SQL for all three files.
     Does NOT require a live DATABASE_URL because --dry-run only reads files.
  2. GET /health/db returns HTTP 200 with {"db": ...} key.
     Tested in two modes:
       a. anon_client raises an exception  → {"db": "error", "detail": ...}
       b. anon_client succeeds             → {"db": "ok"}
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parents[1]
APPLY_SCRIPT = REPO_ROOT / "app" / "db" / "apply.py"


def _env_without_database_url() -> dict:
    """Return the current process environment with DATABASE_URL stripped out.

    Using the real env (not a minimal one) keeps the Python interpreter's
    own sys.path / site-packages intact so imports work correctly.
    """
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    return env


# ---------------------------------------------------------------------------
# 1. apply.py --dry-run
# ---------------------------------------------------------------------------


def test_apply_dry_run_exits_zero():
    """--dry-run reads the SQL files and prints them without needing DATABASE_URL."""
    result = subprocess.run(
        [sys.executable, str(APPLY_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=_env_without_database_url(),
    )
    assert result.returncode == 0, (
        f"apply.py --dry-run exited {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_apply_dry_run_prints_all_files():
    """--dry-run output should mention all three SQL file names."""
    result = subprocess.run(
        [sys.executable, str(APPLY_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=_env_without_database_url(),
    )
    output = result.stdout
    for fname in ("schema.sql", "policies.sql", "triggers.sql"):
        assert fname in output, f"Expected '{fname}' in --dry-run output."


def test_apply_dry_run_output_is_nonempty():
    """--dry-run should produce non-trivial SQL output."""
    result = subprocess.run(
        [sys.executable, str(APPLY_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=_env_without_database_url(),
    )
    # At minimum the schema tables must appear
    assert "create table" in result.stdout.lower(), (
        "Expected 'create table' in --dry-run output."
    )


def test_apply_exits_nonzero_without_database_url():
    """Without DATABASE_URL and without --dry-run, apply.py should exit non-zero."""
    result = subprocess.run(
        [sys.executable, str(APPLY_SCRIPT)],
        capture_output=True,
        text=True,
        env=_env_without_database_url(),
    )
    assert result.returncode != 0, (
        "apply.py should fail with exit code != 0 when DATABASE_URL is missing."
    )
    assert "DATABASE_URL" in result.stdout or "DATABASE_URL" in result.stderr


# ---------------------------------------------------------------------------
# 2. GET /health/db
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return TestClient(app)


def test_health_db_returns_200(client):
    """GET /health/db always returns HTTP 200 (even on DB error)."""
    with patch("app.routers.health.anon_client") as mock_ac:
        # Simulate a successful 0-row query
        mock_table = MagicMock()
        mock_ac.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()
        response = client.get("/health/db")
    assert response.status_code == 200


def test_health_db_ok_when_connected(client):
    """{"db": "ok"} when anon_client query succeeds."""
    with patch("app.routers.health.anon_client") as mock_ac:
        mock_ac.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()
        response = client.get("/health/db")
    assert response.json() == {"db": "ok"}


def test_health_db_error_when_supabase_unreachable(client):
    """{"db": "error", "detail": ...} when anon_client raises an exception."""
    with patch("app.routers.health.anon_client") as mock_ac:
        mock_ac.return_value.table.side_effect = Exception("connection refused")
        response = client.get("/health/db")
    data = response.json()
    assert response.status_code == 200
    assert data["db"] == "error"
    assert "detail" in data
    assert "connection refused" in data["detail"]
