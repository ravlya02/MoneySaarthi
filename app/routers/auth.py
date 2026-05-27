from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db.supabase_client import service_client
from app.dependencies import current_user
from app.models.auth import RegisterPayload, SessionPayload
from app.routers.templates import templates

router = APIRouter(tags=["auth"])


@router.get("/", include_in_schema=False)
async def root(request: Request, settings: Settings = Depends(get_settings)):
    try:
        current_user(request, settings)
        return RedirectResponse("/dashboard", status_code=302)
    except HTTPException:
        return RedirectResponse("/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, settings: Settings = Depends(get_settings)):
    return templates.TemplateResponse(request=request, name="login.html", context={
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    })


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, settings: Settings = Depends(get_settings)):
    return templates.TemplateResponse(request=request, name="register.html", context={
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    })


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
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response
