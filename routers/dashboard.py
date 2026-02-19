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
    get_game_date_range,
    lifetime_net,
    outstanding,
    per_game_net_stddev,
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
    chart_harper_crew_only: Optional[str] = None,
):
    if not require_admin(request):
        return _redirect_login()
    player_ids_filter = request.query_params.getlist("players")
    filter_chart_harper_crew_only = chart_harper_crew_only in ("1", "true", "on", "yes")

    with Session(engine) as session:
        all_players = get_active_players(session)
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
            # Default: first available game to most recent
            range_from, range_to = get_game_date_range(session)
            if range_from is not None and range_to is not None:
                d_from, d_to = range_from, range_to
            else:
                d_to = date.today()
                d_from = d_to - timedelta(days=180)

        # Chart: optionally restrict to Harper crew only for faster filtering
        chart_player_ids = player_ids_filter
        if filter_chart_harper_crew_only:
            harper_ids = [p.id for p in all_players if getattr(p, "harper_crew", False)]
            chart_player_ids = [pid for pid in player_ids_filter if pid in harper_ids]
            if not chart_player_ids and harper_ids:
                chart_player_ids = harper_ids  # show all Harper crew if none in current selection
        chart_json = chart_data(session, chart_player_ids, d_from, d_to)

        # Table: all active players with totals (not filtered by date for table)
        rows = []
        for p in all_players:
            life = lifetime_net(session, p.id)
            sett = settled_net(session, p.id)
            out = outstanding(session, p.id)
            count = games_played_count(session, p.id)
            avg = (life / count) if count else None
            stddev = per_game_net_stddev(session, p.id)
            rows.append({
                "player": p,
                "lifetime_net": life,
                "settled_net": sett,
                "outstanding": out,
                "games_played": count,
                "avg_per_game": avg,
                "net_stddev": stddev,
            })
        # Harper crew first, then by name
        rows.sort(key=lambda r: (not getattr(r["player"], "harper_crew", False), r["player"].name.lower()))

        # Superlatives (require at least 1 game for winner/loser; 5+ for consistency)
        min_games_consistency = 5
        lifetime_winner = max(rows, key=lambda r: r["lifetime_net"]) if rows else None
        lifetime_loser = min(rows, key=lambda r: r["lifetime_net"]) if rows else None
        rows_with_consistency = [r for r in rows if r.get("net_stddev") is not None and r["games_played"] >= min_games_consistency]
        most_consistent = min(rows_with_consistency, key=lambda r: r["net_stddev"]) if rows_with_consistency else None
        most_inconsistent = max(rows_with_consistency, key=lambda r: r["net_stddev"]) if rows_with_consistency else None
        superlatives = {
            "lifetime_winner": lifetime_winner,
            "lifetime_loser": lifetime_loser,
            "most_consistent": most_consistent,
            "most_inconsistent": most_inconsistent,
        }
        total_outstanding = sum(r["outstanding"] for r in rows)

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
            "filter_chart_harper_crew_only": filter_chart_harper_crew_only,
            "flash_message": flash_message or None,
            "flash_type": "success" if flash_message else None,
            "superlatives": superlatives,
            "total_outstanding": total_outstanding,
        },
    )
