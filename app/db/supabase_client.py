from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def anon_client() -> Client:
    """Client with the anon key — RLS is enforced. Use for user-driven reads
    where the request carries the user's JWT."""
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)


@lru_cache
def service_client() -> Client:
    """Client with the service_role key — BYPASSES RLS. Server-side only, used
    exclusively by the background worker to write reports. Never expose this to
    the browser/Jinja layer."""
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)
