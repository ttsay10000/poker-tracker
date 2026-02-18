"""Player CRUD: create, edit, deactivate."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import require_admin
from config import BASE_DIR
from database import engine
from models import Player
from services import get_active_players, get_player_by_id, normalize_name

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


@router.get("/new", response_class=HTMLResponse)
async def player_new_page(request: Request):
    if not require_admin(request):
        return _redirect_login()
    return templates.TemplateResponse("player_new.html", {"request": request})


@router.post("/create")
async def player_create(request: Request):
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return RedirectResponse(url="/players/new?error=name_required", status_code=302)
    name_norm = normalize_name(name)
    with Session(engine) as session:
        existing = session.exec(select(Player).where(Player.name_normalized == name_norm)).first()
        if existing:
            return RedirectResponse(url="/players/new?error=name_exists", status_code=302)
        player = Player(name=name, name_normalized=name_norm)
        session.add(player)
        session.commit()
    return RedirectResponse(url="/dashboard?flash=Player+created", status_code=302)


@router.get("/{player_id}/edit", response_class=HTMLResponse)
async def player_edit_page(request: Request, player_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("player_edit.html", {"request": request, "player": player})


@router.post("/{player_id}/edit")
async def player_edit_post(request: Request, player_id: str):
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return RedirectResponse(url=f"/players/{player_id}/edit?error=name_required", status_code=302)
    name_norm = normalize_name(name)
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
        existing = session.exec(select(Player).where(Player.name_normalized == name_norm).where(Player.id != player_id)).first()
        if existing:
            return RedirectResponse(url=f"/players/{player_id}/edit?error=name_exists", status_code=302)
        player.name = name
        player.name_normalized = name_norm
        session.add(player)
        session.commit()
    return RedirectResponse(url="/dashboard?flash=Player+updated", status_code=302)


@router.post("/{player_id}/deactivate")
async def player_deactivate(request: Request, player_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if player:
            player.is_active = False
            session.add(player)
            session.commit()
    return RedirectResponse(url="/dashboard?flash=Player+deactivated", status_code=302)
