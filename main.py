"""FastAPI app: poker tracker."""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, select

from config import BASE_DIR, DATABASE_URL, UPLOADS_DIR
from database import create_db_and_tables, engine
from templating import templates
from routers import dashboard, games, players, settlements, auth_router, stats
from auth import require_admin
from services import get_active_players
from models import Player
from services import normalize_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Poker Tracker")

# Static and templates
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Make templates available to routers
app.state.templates = templates

# Routers
app.include_router(auth_router.router, tags=["auth"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(players.router, prefix="/players", tags=["players"])
app.include_router(settlements.router, prefix="/settlements", tags=["settlements"])
app.include_router(games.router, prefix="/games", tags=["games"])
app.include_router(stats.router, tags=["stats"])


@app.on_event("startup")
def startup():
    # Only create tables from code when using SQLite (local dev). Production Postgres
    # schema is managed solely by Alembic so alembic_version stays in sync.
    if "sqlite" in DATABASE_URL:
        create_db_and_tables()


@app.get("/health")
async def health():
    """Simple health check: DB connectivity. Returns 200 if DB is reachable, 500 with detail if not."""
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1")).scalar()
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Health check failed")
        return JSONResponse(
            {"status": "error", "detail": str(e)},
            status_code=500,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log unhandled exceptions so Render logs show the real error."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        {"detail": "Internal server error"},
        status_code=500,
    )


@app.get("/")
async def root(request: Request):
    """Redirect to dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/api/players")
async def api_players(request: Request):
    """JSON list of active players for refreshing dropdowns (e.g. after adding a new player)."""
    if not require_admin(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    with Session(engine) as session:
        players_list = get_active_players(session)
    return [{"id": p.id, "name": p.name} for p in players_list]


class CreatePlayerBody(BaseModel):
    name: str


@app.post("/api/players")
async def api_players_create(request: Request, body: CreatePlayerBody):
    """Create a player by name; returns { id, name }. If name already exists (normalized), returns existing player."""
    if not require_admin(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    name = (body.name or "").strip()
    if not name:
        return JSONResponse({"detail": "Name is required"}, status_code=400)
    name_norm = normalize_name(name)
    with Session(engine) as session:
        existing = session.exec(select(Player).where(Player.name_normalized == name_norm)).first()
        if existing:
            return {"id": existing.id, "name": existing.name}
        player = Player(name=name, name_normalized=name_norm)
        session.add(player)
        session.commit()
        session.refresh(player)
    return {"id": player.id, "name": player.name}
