"""Stats hub: leaderboard and filters."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auth import require_admin
from config import BASE_DIR
from database import engine
from stats_services import get_players_for_stats, leaderboard_rows

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


@router.get("/stats", response_class=HTMLResponse)
async def stats_hub(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_inactive: Optional[str] = None,
    min_games: int = 1,
    sort_by: Optional[str] = None,
):
    """Leaderboard with total_net, games_played, win_rate, avg_net_per_game, avg_buyin, outstanding. Filters: date range, include inactive, min games."""
    if not require_admin(request):
        return _redirect_login()
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)
    inc_inactive = include_inactive in ("1", "true", "on", "yes")
    with Session(engine) as session:
        rows = leaderboard_rows(session, d_from, d_to, inc_inactive, min_games)
        # Sort: default total_net desc
        if sort_by == "win_rate":
            rows = sorted(rows, key=lambda r: (r["win_rate"] or 0), reverse=True)
        elif sort_by == "avg_net":
            rows = sorted(rows, key=lambda r: (float(r["avg_net_per_game"]) if r["avg_net_per_game"] is not None else -10**9), reverse=True)
        elif sort_by == "games_played":
            rows = sorted(rows, key=lambda r: r["games_played"], reverse=True)
        else:
            rows = sorted(rows, key=lambda r: float(r["total_net"]), reverse=True)
    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "rows": rows,
            "filter_date_from": date_from or "",
            "filter_date_to": date_to or "",
            "filter_include_inactive": inc_inactive,
            "filter_min_games": min_games,
            "sort_by": sort_by or "total_net",
        },
    )
