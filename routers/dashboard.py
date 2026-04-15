"""Dashboard: chart, totals table, filters."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import require_admin
from config import BASE_DIR
from database import engine
from templating import templates
from models import Player
from services import (
    chart_data,
    games_played_count_map,
    get_active_players,
    get_game_date_range,
    get_paid_up_game_ids,
    lifetime_nets_map,
    outstanding_map,
    per_game_net_stddev_map,
)

router = APIRouter()


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    chart_harper_crew_only: Optional[str] = None,
    table_harper_crew_only: Optional[str] = None,
):
    if not require_admin(request):
        return _redirect_login()
    player_ids_filter = request.query_params.getlist("players")
    filter_chart_harper_crew_only = chart_harper_crew_only in ("1", "true", "on", "yes")
    filter_table_harper_crew_only = table_harper_crew_only in ("1", "true", "on", "yes")

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
        player_ids = [p.id for p in all_players]
        paid_up_ids = get_paid_up_game_ids(session)
        lifetime_nets = lifetime_nets_map(session, player_ids)
        outstanding_values = outstanding_map(session, player_ids, paid_up_game_ids=paid_up_ids)
        games_played = games_played_count_map(session, player_ids)
        stddevs = per_game_net_stddev_map(session, player_ids)
        rows = []
        for p in all_players:
            life = lifetime_nets.get(p.id, 0)
            out = outstanding_values.get(p.id, 0)
            count = games_played.get(p.id, 0)
            avg = (life / count) if count else None
            stddev = stddevs.get(p.id)
            rows.append({
                "player": p,
                "lifetime_net": life,
                "outstanding": out,
                "games_played": count,
                "avg_per_game": avg,
                "net_stddev": stddev,
            })
        # Superlatives (Highlights): always Harper crew only
        harper_rows = [r for r in rows if getattr(r["player"], "harper_crew", False)]

        # Table: optionally restrict to Harper crew only
        if filter_table_harper_crew_only:
            rows = [r for r in rows if getattr(r["player"], "harper_crew", False)]

        # Harper crew first, then by name
        rows.sort(key=lambda r: (not getattr(r["player"], "harper_crew", False), r["player"].name.lower()))

        # Superlatives from harper_rows (require at least 1 game for winner/loser; 5+ for consistency)
        min_games_consistency = 5
        lifetime_winner = max(harper_rows, key=lambda r: r["lifetime_net"]) if harper_rows else None
        lifetime_loser = min(harper_rows, key=lambda r: r["lifetime_net"]) if harper_rows else None
        rows_with_consistency = [r for r in harper_rows if r.get("net_stddev") is not None and r["games_played"] >= min_games_consistency]
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
            "filter_table_harper_crew_only": filter_table_harper_crew_only,
            "flash_message": flash_message or None,
            "flash_type": "success" if flash_message else None,
            "superlatives": superlatives,
            "total_outstanding": total_outstanding,
        },
    )
