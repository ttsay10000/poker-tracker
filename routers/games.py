"""Games: list, manual new, review, confirm, save; edit saved game."""
from datetime import datetime
from decimal import Decimal

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from fastapi import APIRouter

from auth import require_admin
from config import BASE_DIR, BALANCE_EPSILON, UPLOADS_DIR, OPENAI_API_KEY, MAX_UPLOAD_SIZE_BYTES
from database import engine
from extract_game import extract_game
from game_forms import parse_game_form
from models import Game, GameEntry
from services import get_active_players, has_any_settlements, settlements_affect_players

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _form_dict(request_form) -> dict:
    """Build a plain dict from form (works with Starlette FormData and dict-like)."""
    if request_form is None:
        return {}
    try:
        keys = request_form.keys() if hasattr(request_form, "keys") else []
        return {k: request_form.get(k) for k in keys}
    except Exception:
        return {}


def _rows_for_template(rows: list) -> list:
    """Convert parsed rows to template-friendly dicts (Decimal -> str for form values)."""
    out = []
    for r in rows:
        out.append({
            "player_id": r["player_id"] or "",
            "raw_name": r["raw_name"] or "",
            "buyin": str(r["buyin"]) if r["buyin"] is not None else "",
            "cashout": str(r["cashout"]) if r["cashout"] is not None else "",
            "final_stack": str(r["final_stack"]) if r["final_stack"] is not None else "",
            "net_change": str(r["net_change"]) if r["net_change"] is not None else "",
            "errors": r.get("errors", []),
        })
    return out


# ---- List ----
@router.get("", response_class=HTMLResponse)
async def game_list(request: Request):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        games = list(session.exec(select(Game).order_by(Game.played_at.desc())).all())
        # Load entry count and balanced per game
        game_list_data = []
        for g in games:
            entries = list(session.exec(select(GameEntry).where(GameEntry.game_id == g.id)).all())
            total = sum(e.net_change for e in entries)
            game_list_data.append({"game": g, "entry_count": len(entries), "balanced": abs(total) <= BALANCE_EPSILON})
    return templates.TemplateResponse("game_list.html", {"request": request, "game_list_data": game_list_data})


# ---- Legacy redirects (single "Add game" flow now) ----
@router.get("/new/manual", response_class=HTMLResponse)
async def _redirect_new_manual(request: Request, date: str = ""):
    if not require_admin(request):
        return _redirect_login()
    return RedirectResponse(url=f"/games/new?date={date}" if date else "/games/new", status_code=302)


@router.get("/new/upload", response_class=HTMLResponse)
async def _redirect_new_upload(request: Request):
    if not require_admin(request):
        return _redirect_login()
    return RedirectResponse(url="/games/new", status_code=302)


# ---- Add game: single step 1 (date + screenshots and/or notes) -> step 2 (review) ----
@router.get("/new", response_class=HTMLResponse)
async def new_game_page(request: Request, date: str = "", flash: str = ""):
    if not require_admin(request):
        return _redirect_login()
    flash_message = flash.replace("+", " ") if flash else None
    flash_type = "success" if flash_message and "saved" in flash_message.lower() else ("error" if flash_message else None)
    return templates.TemplateResponse(
        "game_new.html",
        {
            "request": request,
            "prefill_date": date or "",
            "flash_message": flash_message,
            "flash_type": flash_type,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def new_game_post(request: Request):
    if not require_admin(request):
        return _redirect_login()
    import uuid
    try:
        form = await request.form()
    except Exception:
        return templates.TemplateResponse(
            "game_new.html",
            {
                "request": request,
                "prefill_date": "",
                "flash_message": "Invalid form data. Please try again.",
                "flash_type": "error",
            },
        )
    played_at_str = (form.get("played_at") or "").strip()
    notes = (form.get("notes") or "").strip()
    played_at = None
    if played_at_str:
        try:
            from datetime import date as date_type
            d = date_type.fromisoformat(played_at_str)
            played_at = datetime.combine(d, datetime.min.time())
        except ValueError:
            pass

    # Collect uploaded image files (multiple); tolerate write failures
    files = form.getlist("files") if hasattr(form, "getlist") else []
    if not files and "files" in form:
        f = form.get("files")
        if f and hasattr(f, "filename") and f.filename:
            files = [f]
    saved_paths = []
    source_image_path_or_url = None
    upload_size_error = False
    for file in files:
        if not hasattr(file, "filename") or not file.filename:
            continue
        ext = (file.filename or "").split(".")[-1] or "png"
        if ext.lower() not in ("png", "jpg", "jpeg", "gif", "webp"):
            ext = "png"
        name = f"{uuid.uuid4().hex}.{ext}"
        path = UPLOADS_DIR / name
        try:
            body = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
            if len(body) > MAX_UPLOAD_SIZE_BYTES:
                upload_size_error = True
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)
        except Exception:
            continue
        saved_paths.append(path)
        if source_image_path_or_url is None:
            source_image_path_or_url = f"/uploads/{name}"

    # Extract from notes and/or images via LLM
    rows = [{"player_id": "", "raw_name": "", "buyin": "", "cashout": "", "final_stack": "", "net_change": "", "errors": []}]
    if OPENAI_API_KEY and (notes or saved_paths):
        try:
            extracted = extract_game(notes=notes or None, image_paths=saved_paths or None)
            if extracted:
                rows = [
                    {
                        "player_id": "",
                        "raw_name": r.get("raw_name", "") or "",
                        "buyin": r.get("buyin", "") or "",
                        "cashout": r.get("cashout", "") or "",
                        "final_stack": r.get("final_stack", "") or "",
                        "net_change": r.get("net_change", "") or "",
                        "errors": [],
                    }
                    for r in extracted
                ]
        except Exception:
            pass

    try:
        with Session(engine) as session:
            players = get_active_players(session)
    except Exception:
        return templates.TemplateResponse(
            "game_new.html",
            {
                "request": request,
                "prefill_date": played_at_str or "",
                "flash_message": "Database error. Please try again.",
                "flash_type": "error",
            },
        )

    def _row_net(r):
        v = r.get("net_change") or ""
        if not v:
            return Decimal(0)
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal(0)
    sum_net = sum((_row_net(r) for r in rows), Decimal(0))
    balanced = abs(sum_net) <= BALANCE_EPSILON
    extracted_any = bool(rows and (rows[0].get("raw_name") or rows[0].get("net_change")))
    errors_list = []
    if upload_size_error:
        errors_list.append("Some files were too large (max 10 MB per file) and were skipped.")
    try:
        return templates.TemplateResponse(
            "game_review.html",
            {
                "request": request,
                "played_at": played_at,
                "played_at_iso": played_at.strftime("%Y-%m-%d") if played_at else "",
                "source_image_path_or_url": source_image_path_or_url or "",
                "game_id": None,
                "rows": rows,
                "players": players,
                "sum_net": sum_net,
                "balanced": balanced,
                "delta": sum_net,
                "errors": errors_list,
                "force_save": False,
                "force_reason": "",
                "extracted_from_screenshot": extracted_any,
            },
        )
    except Exception:
        return templates.TemplateResponse(
            "game_new.html",
            {
                "request": request,
                "prefill_date": played_at_str or "",
                "flash_message": "Something went wrong. Please try again.",
                "flash_type": "error",
            },
        )


# ---- Review: POST with full grid -> validate; re-render or show confirm ----
@router.post("/review", response_class=HTMLResponse)
async def review_post(request: Request):
    if not require_admin(request):
        return _redirect_login()
    try:
        form = await request.form()
        data = parse_game_form(_form_dict(form))
    except Exception:
        return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
    with Session(engine) as session:
        players = get_active_players(session)
    if data["errors"]:
        return templates.TemplateResponse(
            "game_review.html",
            {
                "request": request,
                "played_at": data["played_at"],
                "played_at_iso": data["played_at"].strftime("%Y-%m-%d") if data["played_at"] else "",
                "source_image_path_or_url": data["source_image_path_or_url"] or "",
                "game_id": None,
                "rows": _rows_for_template(data["rows"]),
                "players": players,
                "sum_net": data["sum_net"],
                "balanced": data["balanced"],
                "delta": data["delta"],
                "errors": data["errors"],
                "force_save": data["force_save"],
                "force_reason": data["force_reason"] or "",
                "edit_mode": False,
            },
        )
    # Valid: show confirm page (no DB write)
    player_names = {p.id: p.name for p in players}
    return templates.TemplateResponse(
        "game_confirm.html",
        {
            "request": request,
            "parsed": data,
            "players": players,
            "player_names": player_names,
            "game_id": None,
        },
    )


# ---- Confirm: POST to save (only DB write here) ----
@router.post("/save", response_class=HTMLResponse)
async def save_post(request: Request, add_another: str = ""):
    if not require_admin(request):
        return _redirect_login()
    try:
        form = await request.form()
        data = parse_game_form(_form_dict(form))
    except Exception:
        return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
    if data["errors"]:
        with Session(engine) as session:
            players = get_active_players(session)
        return templates.TemplateResponse(
            "game_review.html",
            {
                "request": request,
                "played_at": data["played_at"],
                "played_at_iso": data["played_at"].strftime("%Y-%m-%d") if data["played_at"] else "",
                "source_image_path_or_url": data["source_image_path_or_url"] or "",
                "game_id": None,
                "rows": _rows_for_template(data["rows"]),
                "players": players,
                "sum_net": data["sum_net"],
                "balanced": data["balanced"],
                "delta": data["delta"],
                "errors": data["errors"],
                "force_save": data["force_save"],
                "force_reason": data["force_reason"] or "",
                "edit_mode": False,
            },
        )
    with Session(engine) as session:
        game = Game(
            played_at=data["played_at"],
            source_image_path_or_url=data["source_image_path_or_url"],
        )
        session.add(game)
        session.flush()
        for r in data["rows"]:
            if not r["player_id"] or r["net_change"] is None:
                continue
            entry = GameEntry(
                game_id=game.id,
                player_id=r["player_id"],
                raw_name=r["raw_name"],
                buyin=r["buyin"],
                cashout=r["cashout"],
                final_stack=r["final_stack"],
                net_change=r["net_change"],
            )
            session.add(entry)
        session.commit()
    redirect_url = "/dashboard?flash=Game+saved"
    if add_another and data["played_at"]:
        redirect_url = f"/games/new?date={data['played_at'].strftime('%Y-%m-%d')}&flash=Game+saved"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---- Edit saved game ----
@router.get("/{game_id}", response_class=HTMLResponse)
async def game_edit_page(request: Request, game_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        game = session.get(Game, game_id)
        if not game:
            return RedirectResponse(url="/games", status_code=302)
        entries = list(session.exec(select(GameEntry).where(GameEntry.game_id == game_id)).all())
        players = get_active_players(session)
        rows = [
            {
                "player_id": e.player_id,
                "raw_name": e.raw_name or "",
                "buyin": str(e.buyin) if e.buyin is not None else "",
                "cashout": str(e.cashout) if e.cashout is not None else "",
                "final_stack": str(e.final_stack) if e.final_stack is not None else "",
                "net_change": str(e.net_change) if e.net_change is not None else "",
                "errors": [],
            }
            for e in entries
        ]
        if not rows:
            rows = [{"player_id": "", "raw_name": "", "buyin": "", "cashout": "", "final_stack": "", "net_change": "", "errors": []}]
        sum_net = sum(e.net_change for e in entries)
        balanced = abs(sum_net) <= BALANCE_EPSILON
        has_settlements = has_any_settlements(session)
    return templates.TemplateResponse(
        "game_review.html",
        {
            "request": request,
            "played_at": game.played_at,
            "played_at_iso": game.played_at.strftime("%Y-%m-%d"),
            "source_image_path_or_url": game.source_image_path_or_url or "",
            "game_id": game_id,
            "rows": rows,
            "players": players,
            "sum_net": sum_net,
            "balanced": balanced,
            "delta": sum_net,
            "errors": [],
            "force_save": False,
            "force_reason": "",
            "edit_mode": True,
            "has_settlements": has_settlements,
        },
    )


@router.post("/{game_id}/save", response_class=HTMLResponse)
async def game_edit_save(request: Request, game_id: str, add_another: str = ""):
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    data = parse_game_form(_form_dict(form))
    if data["errors"]:
        with Session(engine) as session:
            players = get_active_players(session)
        return templates.TemplateResponse(
            "game_review.html",
            {
                "request": request,
                "played_at": data["played_at"],
                "played_at_iso": data["played_at"].strftime("%Y-%m-%d") if data["played_at"] else "",
                "source_image_path_or_url": data["source_image_path_or_url"] or "",
                "game_id": game_id,
                "rows": _rows_for_template(data["rows"]),
                "players": players,
                "sum_net": data["sum_net"],
                "balanced": data["balanced"],
                "delta": data["delta"],
                "errors": data["errors"],
                "force_save": data["force_save"],
                "force_reason": data["force_reason"] or "",
                "edit_mode": True,
            },
        )
    with Session(engine) as session:
        game = session.get(Game, game_id)
        if not game:
            return RedirectResponse(url="/games", status_code=302)
        player_ids = [r["player_id"] for r in data["rows"] if r["player_id"]]
        warn_settlements = settlements_affect_players(session, player_ids)
        game.played_at = data["played_at"]
        game.source_image_path_or_url = data["source_image_path_or_url"]
        game.updated_at = datetime.utcnow()
        session.add(game)
        for entry in session.exec(select(GameEntry).where(GameEntry.game_id == game_id)).all():
            session.delete(entry)
        session.flush()
        for r in data["rows"]:
            if not r["player_id"] or r["net_change"] is None:
                continue
            entry = GameEntry(
                game_id=game.id,
                player_id=r["player_id"],
                raw_name=r["raw_name"],
                buyin=r["buyin"],
                cashout=r["cashout"],
                final_stack=r["final_stack"],
                net_change=r["net_change"],
            )
            session.add(entry)
        session.commit()
    flash = "Game updated."
    if warn_settlements:
        flash += " Outstanding balances have changed (settlements were not auto-adjusted)."
    return RedirectResponse(url=f"/dashboard?flash={flash.replace(' ', '+')}", status_code=302)
