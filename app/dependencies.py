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


def current_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser:
    """Verify the Supabase JWT and return the authenticated user.

    user_id is always derived from the verified token (auth.uid()), never the
    request body — see CLAUDE.md guardrails.
    """
    token = _extract_token(request)
    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return CurrentUser(id=claims["sub"], email=claims.get("email"))
