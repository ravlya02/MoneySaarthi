from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import auth, dashboard, health, onboarding

app = FastAPI(title="MoneySaarthi", version="0.1.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(onboarding.router)
app.include_router(dashboard.router)
app.include_router(health.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
