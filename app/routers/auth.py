from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.routers.templates import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# Auth itself is handled by Supabase Auth on the client; the backend only
# verifies the resulting JWT (see app/dependencies.py current_user).
