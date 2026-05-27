from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt

from app.config import Settings, get_settings


@dataclass
class CurrentUser:
    id: str
    email: str | None = None


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    token = request.cookies.get("access_token")
    if token:
        return token
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")


def optional_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser | None:
    """Returns CurrentUser or None — never raises. Safe for public pages that
    only need to *check* auth (e.g. redirect already-signed-in visitors away
    from /login and /register)."""
    try:
        return current_user(request, settings)
    except HTTPException:
        return None


def current_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser:
    """Verify the Supabase JWT and return the authenticated user.

    Two-stage verification:
    1. Fast local decode using SUPABASE_JWT_SECRET (no network; required for tests).
    2. If the secret is empty/wrong, fall back to Supabase Auth API (get_user).
       This handles the common case where .env has a stale or missing JWT secret.

    user_id is always derived from the verified token, never the request body.
    """
    token = _extract_token(request)

    # ── Stage 1: local decode (fast; works when secret is correct) ──────────
    if settings.supabase_jwt_secret:
        try:
            claims = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
            return CurrentUser(id=claims["sub"], email=claims.get("email"))
        except JWTError:
            pass  # secret mismatch → fall through to API verification

    # ── Stage 2: Supabase API verification (no local secret needed) ─────────
    try:
        from app.db.supabase_client import anon_client  # lazy to avoid circular import
        resp = anon_client().auth.get_user(token)
        if resp.user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
        return CurrentUser(id=str(resp.user.id), email=resp.user.email)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
