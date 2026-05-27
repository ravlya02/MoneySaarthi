from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db.supabase_client import service_client
from app.dependencies import current_user, optional_user
from app.models.auth import LoginPayload, RegisterPayload, SessionPayload
from app.routers.templates import templates

router = APIRouter(tags=["auth"])


@router.get("/", include_in_schema=False)
async def root(request: Request, settings: Settings = Depends(get_settings)):
    try:
        current_user(request, settings)
        return RedirectResponse("/dashboard", status_code=302)
    except HTTPException:
        return RedirectResponse("/login", status_code=302)


def _safe_next(next_url: str) -> str:
    """Return next_url only if it is a safe relative path; else /dashboard.
    Prevents open-redirect attacks via /login?next=//evil.com."""
    return next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: str = "/dashboard",
    logged_out: bool = False,
    settings: Settings = Depends(get_settings),
):
    # Bounce already-authenticated users straight to their destination.
    user = optional_user(request, settings)
    if user:
        return RedirectResponse(_safe_next(next), status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "next_url": _safe_next(next),
        "logged_out": logged_out,
    })


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, settings: Settings = Depends(get_settings)):
    # Bounce already-authenticated users to the dashboard.
    user = optional_user(request, settings)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request=request, name="register.html")


@router.post("/register", status_code=201)
async def register(payload: RegisterPayload):
    """Create a new user via the admin API with email already confirmed.

    Uses the service_role key (server-side only — never reaches the browser).
    email_confirm=True bypasses Supabase's email-verification gate entirely so
    the user can sign in immediately after account creation.
    user_metadata carries full_name for the on_auth_user_created trigger.
    """
    try:
        service_client().auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
            "user_metadata": {"full_name": payload.full_name},
        })
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/login", status_code=204)
async def login_user(
    payload: LoginPayload,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Server-side sign-in — no Supabase JS required.

    Creates a fresh client per request (avoids shared session state from the
    cached anon_client). If Supabase returns 'Email not confirmed' the admin API
    auto-confirms the account and retries, so existing unconfirmed accounts are
    silently healed on first login.
    """
    from supabase import create_client as _create

    sb = _create(settings.supabase_url, settings.supabase_anon_key)

    def _do_signin():
        return sb.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )

    try:
        result = _do_signin()
    except Exception as exc:
        if "not confirmed" in str(exc).lower():
            # Heal legacy / unconfirmed accounts: find by email, force-confirm, retry.
            try:
                all_users = service_client().auth.admin.list_users()
                user = next((u for u in all_users if u.email == payload.email), None)
                if user:
                    service_client().auth.admin.update_user_by_id(
                        str(user.id), {"email_confirm": True}
                    )
                    result = _do_signin()  # retry after confirmation
                else:
                    raise HTTPException(status_code=400, detail="Account not found.") from exc
            except HTTPException:
                raise
            except Exception as exc2:
                raise HTTPException(status_code=400, detail=str(exc2)) from exc2
        else:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    response.set_cookie(
        key="access_token",
        value=result.session.access_token,
        httponly=True,
        samesite="lax",
        max_age=3600,
        secure=not settings.debug,
    )


@router.post("/auth/session", status_code=204)
async def set_session(
    payload: SessionPayload,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    response.set_cookie(
        key="access_token",
        value=payload.access_token,
        httponly=True,
        samesite="lax",
        max_age=3600,
        secure=not settings.debug,
    )


@router.post("/auth/logout")
async def logout(response: Response):
    response = RedirectResponse("/login?logged_out=1", status_code=302)
    response.delete_cookie("access_token")
    return response
