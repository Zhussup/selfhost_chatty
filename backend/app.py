"""FastAPI app factory: /api routers (guarded), then static frontend mount."""

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend import db
from backend.auth import require_user
from backend.config import settings
from backend.routes import auth_routes, chat, models, sessions, stats

app = FastAPI(title="selfhost_chat", docs_url=None, redoc_url=None)

api = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
api.include_router(models.router)
api.include_router(sessions.router)
api.include_router(stats.router)

# chat + auth are mounted at /api level directly (auth handles its own exclusions)
app.include_router(auth_routes.router)
app.include_router(chat.router)
app.include_router(api)

# init DB schema at import so the first request never races the DDL
db.init()

# serve the built SPA (frontend/dist) last so /api routes win
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="static")
else:
    # no built frontend yet: smoke console instead of a bare 404
    _console = (Path(__file__).resolve().parent / "smoke_console.html").read_text(encoding="utf-8")

    @app.get("/", include_in_schema=False)
    async def root_console() -> HTMLResponse:
        return HTMLResponse(_console)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "model_default": settings.default_model or None}