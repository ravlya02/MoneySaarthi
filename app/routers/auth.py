from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.dependencies import current_user
from app.models.auth import SessionPayload
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
