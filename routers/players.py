"""Player CRUD: create, edit, deactivate; profile and photo upload."""
import os
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, func, select

from auth import require_admin
from config import BASE_DIR, UPLOADS_DIR, MAX_UPLOAD_SIZE_BYTES
from database import engine
from templating import templates
from models import Expense, GameEntry, Player, Settlement
from services import get_active_players, get_player_by_id, normalize_name, outstanding
from stats_services import (
    chart_data_single_player,
    leaderboard_rows,
    lineup_with_x_stats,
    most_frequent_best_friend_nemesis,
    player_core_stats,
    player_streaks,
    player_activity_log,
    rivalry_badges_windows,
    rivalry_monthly_counts,
)

router = APIRouter()

ALLOWED_PHOTO_EXT = frozenset({"jpg", "jpeg", "png", "gif", "webp"})


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


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


@router.get("/{player_id}", response_class=HTMLResponse)
async def player_profile(
    request: Request,
    player_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_sample: int = 5,
):
    """Player profile: edit card, photo, snapshot stats, chart, recent games, with-X table, rivalry."""
    if not require_admin(request):
        return _redirect_login()
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
        core = player_core_stats(session, player_id, d_from, d_to)
        streaks = player_streaks(session, player_id, d_from, d_to)
        chart = chart_data_single_player(session, player_id, d_from, d_to)
        activity_log = player_activity_log(session, player_id, date_from=d_from, date_to=d_to)
        with_x = lineup_with_x_stats(session, player_id, d_from, d_to, min_sample)
        rivalry = rivalry_badges_windows(session, player_id, d_from, d_to, min_sample)
        monthly = rivalry_monthly_counts(session, player_id, min_games_in_month=2, min_sample_month=2)
        mf = most_frequent_best_friend_nemesis(session, player_id, min_games_in_month=2, min_sample_month=2)
        out = outstanding(session, player_id)
    return templates.TemplateResponse(
        "player_profile.html",
        {
            "request": request,
            "player": player,
            "core": core,
            "streaks": streaks,
            "chart_data": chart,
            "activity_log": activity_log,
            "with_x_rows": with_x,
            "rivalry": rivalry,
            "rivalry_monthly": monthly,
            "most_frequent": mf,
            "outstanding": out,
            "filter_date_from": date_from or "",
            "filter_date_to": date_to or "",
            "filter_min_sample": min_sample,
        },
    )


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
    venmo = (form.get("venmo_handle") or "").strip() or None
    zelle = (form.get("zelle_handle") or "").strip() or None
    notes = (form.get("notes") or "").strip() or None
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
        existing = session.exec(select(Player).where(Player.name_normalized == name_norm).where(Player.id != player_id)).first()
        if existing:
            return RedirectResponse(url=f"/players/{player_id}/edit?error=name_exists", status_code=302)
        player.name = name
        player.name_normalized = name_norm
        player.venmo_handle = venmo
        player.zelle_handle = zelle
        player.notes = notes
        # Only update harper_crew when form is from full edit page (profile quick-edit has no checkbox)
        if "from_full_edit" in form:
            player.harper_crew = "harper_crew" in form
        session.add(player)
        session.commit()
    return RedirectResponse(url=f"/players/{player_id}?flash=Profile+updated", status_code=302)


@router.post("/{player_id}/photo")
async def player_photo_upload(request: Request, player_id: str, photo: UploadFile = File(...)):
    if not require_admin(request):
        return _redirect_login()
    filename = (photo.filename or "").strip()
    ext = Path(filename).suffix.lstrip(".").lower() if filename else ""
    if ext not in ALLOWED_PHOTO_EXT:
        return RedirectResponse(url=f"/players/{player_id}?error=invalid_photo", status_code=302)
    players_dir = UPLOADS_DIR / "players"
    players_dir.mkdir(parents=True, exist_ok=True)
    # Remove old photo file if any (same player_id, any ext)
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
        old_path = player.photo_path_or_url
        if old_path:
            # Prevent path traversal: only delete files under UPLOADS_DIR
            old_full = (UPLOADS_DIR / old_path).resolve()
            try:
                old_full.relative_to(UPLOADS_DIR.resolve())
            except (ValueError, TypeError):
                pass  # path outside uploads dir, skip delete
            else:
                if old_full.is_file():
                    try:
                        old_full.unlink()
                    except OSError:
                        pass
        save_name = f"{player_id}.{ext}"
        rel_path = f"players/{save_name}"
        full_path = UPLOADS_DIR / rel_path
        contents = await photo.read(MAX_UPLOAD_SIZE_BYTES + 1)
        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            return RedirectResponse(url=f"/players/{player_id}?error=file_too_large", status_code=302)
        full_path.write_bytes(contents)
        player.photo_path_or_url = rel_path
        session.add(player)
        session.commit()
    return RedirectResponse(url=f"/players/{player_id}?flash=Photo+updated", status_code=302)


@router.get("/{player_id}/deactivate", response_class=HTMLResponse)
async def player_deactivate_page(request: Request, player_id: str):
    """Deactivate options: merge data into another player, or delete and lose game data."""
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
        # Other active players (excluding self) for merge target
        merge_targets = [p for p in get_active_players(session) if p.id != player_id]
        entry_count = session.exec(select(func.count(GameEntry.id)).where(GameEntry.player_id == player_id)).one() or 0
        settlement_count = session.exec(select(func.count(Settlement.id)).where(Settlement.player_id == player_id)).one() or 0
    return templates.TemplateResponse(
        "player_deactivate.html",
        {
            "request": request,
            "player": player,
            "merge_targets": merge_targets,
            "game_entry_count": entry_count,
            "settlement_count": settlement_count,
        },
    )


@router.post("/{player_id}/deactivate/merge")
async def player_deactivate_merge(request: Request, player_id: str):
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    target_player_id = (form.get("target_player_id") or "").strip()
    if not target_player_id or target_player_id == player_id:
        return RedirectResponse(url=f"/players/{player_id}/deactivate?error=invalid_target", status_code=302)
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        target = get_player_by_id(session, target_player_id)
        if not player or not target or not target.is_active:
            return RedirectResponse(url="/dashboard", status_code=302)
        # Reassign all game entries, settlements, and expenses to target
        for entry in session.exec(select(GameEntry).where(GameEntry.player_id == player_id)).all():
            entry.player_id = target_player_id
            session.add(entry)
        for settlement in session.exec(select(Settlement).where(Settlement.player_id == player_id)).all():
            settlement.player_id = target_player_id
            session.add(settlement)
        for expense in session.exec(select(Expense).where(Expense.player_id == player_id)).all():
            expense.player_id = target_player_id
            session.add(expense)
        player.is_active = False
        session.add(player)
        session.commit()
    return RedirectResponse(url="/dashboard?flash=Player+merged+and+deactivated", status_code=302)


@router.post("/{player_id}/deactivate/delete")
async def player_deactivate_delete(request: Request, player_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if not player:
            return RedirectResponse(url="/dashboard", status_code=302)
        # Delete dependent rows first, then player.
        for entry in session.exec(select(GameEntry).where(GameEntry.player_id == player_id)).all():
            session.delete(entry)
        for settlement in session.exec(select(Settlement).where(Settlement.player_id == player_id)).all():
            session.delete(settlement)
        for expense in session.exec(select(Expense).where(Expense.player_id == player_id)).all():
            session.delete(expense)
        session.delete(player)
        session.commit()
    return RedirectResponse(url="/dashboard?flash=Player+and+all+game+data+deleted", status_code=302)


@router.post("/{player_id}/deactivate")
async def player_deactivate(request: Request, player_id: str):
    """Just deactivate (keep data); use deactivate page for merge/delete."""
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        player = get_player_by_id(session, player_id)
        if player:
            player.is_active = False
            session.add(player)
            session.commit()
    return RedirectResponse(url="/dashboard?flash=Player+deactivated", status_code=302)
