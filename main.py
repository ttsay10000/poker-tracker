"""FastAPI app: poker tracker."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from config import BASE_DIR, UPLOADS_DIR
from database import create_db_and_tables, engine
from routers import dashboard, games, players, settlements, auth_router, stats
from auth import require_admin
from services import get_active_players

app = FastAPI(title="Poker Tracker")

# Static and templates
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Make templates available to routers
app.state.templates = templates

# Routers
app.include_router(auth_router.router, tags=["auth"])
app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(players.router, prefix="/players", tags=["players"])
app.include_router(settlements.router, prefix="/settlements", tags=["settlements"])
app.include_router(games.router, prefix="/games", tags=["games"])
app.include_router(stats.router, tags=["stats"])


@app.on_event("startup")
def startup():
    create_db_and_tables()


@app.get("/")
async def root(request: Request):
    """Redirect to dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/api/players")
async def api_players(request: Request):
    """JSON list of active players for refreshing dropdowns (e.g. after adding a new player)."""
    if not require_admin(request):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    with Session(engine) as session:
        players_list = get_active_players(session)
    return [{"id": p.id, "name": p.name} for p in players_list]
