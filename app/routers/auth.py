from urllib.parse import quote as _urlquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db.supabase_client import anon_client, service_client
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
    error: str = "",
    settings: Settings = Depends(get_settings),
):
    # Bounce already-authenticated users straight to their destination.
    user = optional_user(request, settings)
    if user:
        return RedirectResponse(_safe_next(next), status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "next_url": _safe_next(next),
        "logged_out": logged_out,
        "login_error": error,
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


@router.post("/auth/login")
async def login_user(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Server-side sign-in — no Supabase JS required.

    Supports two call styles:
    • JSON body (Content-Type: application/json) — used by register.html's fetch();
      returns 204 + Set-Cookie on success, 400 JSON on failure.
    • Form data (Content-Type: application/x-www-form-urlencoded) — used by the
      native POST from login.html; returns 303 → /dashboard on success,
      303 → /login?error=… on failure (browser handles navigation; no JS redirect).
    """
    is_json = "application/json" in request.headers.get("content-type", "")

    if is_json:
        body = LoginPayload(**await request.json())
        email, password = body.email, body.password
        dest = "/dashboard"
    else:
        form = await request.form()
        email = str(form.get("email", ""))
        password = str(form.get("password", ""))
        dest = _safe_next(str(form.get("next", "/dashboard")))

    try:
        result = anon_client().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except Exception as exc:
        if is_json:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Server-side redirect back to login with the error visible in the page.
        return RedirectResponse(
            f"/login?error={_urlquote(str(exc), safe='')}&next={dest}",
            status_code=303,
        )

    _cookie = dict(
        key="access_token",
        value=result.session.access_token,
        httponly=True,
        samesite="lax",
        max_age=3600,
        secure=not settings.debug,
    )

    if is_json:
        # Existing API behaviour: 204 + Set-Cookie (used by register.html fetch).
        r = Response(status_code=204)
        r.set_cookie(**_cookie)
        return r

    # Form path: 303 redirect — browser follows it with the cookie already set.
    r = RedirectResponse(dest, status_code=303)
    r.set_cookie(**_cookie)
    return r


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
