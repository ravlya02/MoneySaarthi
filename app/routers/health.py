"""Health-check router.

GET /health/db — lightweight database connectivity probe using the anon client
(same connection path as user-facing requests). Returns HTTP 200 in both the
healthy and unhealthy cases so deployment health checks can read the JSON body
without tripping on a non-2xx status.

This router intentionally uses the *anon* client (not service_role) so the probe
validates the trust path that the application layer actually exercises.
"""
from fastapi import APIRouter

from app.db.supabase_client import anon_client

router = APIRouter(tags=["health"])


@router.get("/health/db")
async def db_health() -> dict:
    """Check Supabase PostgREST connectivity.

    Runs a zero-row SELECT against the ``profiles`` table via the anon key.
    A successful response (even an empty result set) confirms:
    - The SUPABASE_URL and SUPABASE_ANON_KEY are valid.
    - The PostgREST layer is reachable.
    - The ``profiles`` table exists (schema was applied).

    Returns ``{"db": "ok"}`` on success or ``{"db": "error", "detail": "..."}``
    on failure. HTTP 200 in both cases.
    """
    try:
        # A 0-row query is enough to validate connectivity and schema existence.
        anon_client().table("profiles").select("id").limit(0).execute()
        return {"db": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"db": "error", "detail": str(exc)}
