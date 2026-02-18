"""Dashboard: chart, totals table, filters."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import require_admin
from config import BASE_DIR
from database import engine
from models import Player
from services import (
    chart_data,
    games_played_count,
    get_active_players,
    lifetime_net,
    outstanding,
    settled_net,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    if not require_admin(request):
        return _redirect_login()
    player_ids_filter = request.query_params.getlist("players")

    with Session(engine) as session:
        all_players = get_active_players(session)
        if not player_ids_filter:
            player_ids_filter = [p.id for p in all_players]
        if not player_ids_filter:
            player_ids_filter = [p.id for p in all_players]

        d_from = None
        d_to = None
        if date_from:
            try:
                d_from = date.fromisoformat(date_from)
            except ValueError:
                pass
        if date_to:
            try:
                d_to = date.fromisoformat(date_to)
            except ValueError:
                pass
        if not d_from and not d_to:
            # Default: last 6 months
            d_to = date.today()
            d_from = d_to - timedelta(days=180)

        chart_json = chart_data(session, player_ids_filter, d_from, d_to)

        # Table: all active players with totals (not filtered by date for table)
        rows = []
        for p in all_players:
            life = lifetime_net(session, p.id)
            sett = settled_net(session, p.id)
            out = outstanding(session, p.id)
            count = games_played_count(session, p.id)
            avg = (life / count) if count else None
            rows.append({
                "player": p,
                "lifetime_net": life,
                "settled_net": sett,
                "outstanding": out,
                "games_played": count,
                "avg_per_game": avg,
            })

    flash_message = request.query_params.get("flash", "").replace("+", " ")
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "rows": rows,
            "chart_data": chart_json,
            "filter_players": all_players,
            "filter_player_ids": player_ids_filter,
            "filter_date_from": d_from.isoformat() if d_from else "",
            "filter_date_to": d_to.isoformat() if d_to else "",
            "flash_message": flash_message or None,
            "flash_type": "success" if flash_message else None,
        },
    )
