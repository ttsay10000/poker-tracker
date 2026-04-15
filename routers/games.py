"""Games: list, manual new, review, confirm, save; edit saved game."""
import logging
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from fastapi import APIRouter

from auth import require_admin, check_payment_unlocked_redirect
from config import (
    BASE_DIR,
    BALANCE_EPSILON,
    MAX_EXTRACT_IMAGE_BYTES,
    MAX_EXTRACT_IMAGE_COUNT,
    MAX_EXTRACT_TOTAL_BYTES,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_SIZE_BYTES,
    OPENAI_API_KEY,
    PLAYER_ALIASES,
    UPLOADS_DIR,
)
from database import engine
from extract_game import extract_game
from game_forms import parse_game_form, parse_multi_game_form
from models import Game, GameEntry, Player, Settlement
from services import get_active_players, has_any_settlements, settlements_affect_players, settlements_for_game, settlements_to_remove_for_game, normalize_name
from templating import templates

router = APIRouter()
logger = logging.getLogger(__name__)


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _resolve_new_players(session: Session, rows: list[dict]) -> None:
    """Create players for rows with player_id '__new__' using raw_name, before any game data is assigned."""
    for r in rows:
        if (r.get("player_id") or "").strip() != "__new__":
            continue
        name = (r.get("raw_name") or "").strip() or "New Player"
        name_norm = normalize_name(name)
        existing = session.exec(select(Player).where(Player.name_normalized == name_norm)).first()
        if existing:
            r["player_id"] = existing.id
        else:
            player = Player(name=name, name_normalized=name_norm)
            session.add(player)
            session.flush()
            r["player_id"] = player.id


def _form_dict(request_form) -> dict:
    """Build a plain dict from form (works with Starlette FormData and dict-like)."""
    if request_form is None:
        return {}
    try:
        keys = request_form.keys() if hasattr(request_form, "keys") else []
        return {k: request_form.get(k) for k in keys}
    except Exception:
        return {}


def _to_decimal(v: Any) -> Decimal:
    """Coerce value (str, int, float, Decimal, None) to Decimal for arithmetic. Safe for extraction output."""
    if v is None or v == "":
        return Decimal(0)
    try:
        return Decimal(str(v).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _blank_review_row() -> dict[str, Any]:
    return {
        "player_id": "",
        "raw_name": "",
        "buyin": "",
        "cashout": "",
        "final_stack": "",
        "net_change": "",
        "errors": [],
    }


def _file_size(path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _format_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _extraction_limit_error(paths: list, screenshot_grouping: str) -> Optional[str]:
    if not paths:
        return None
    if len(paths) > MAX_EXTRACT_IMAGE_COUNT:
        if screenshot_grouping == "one_game":
            return (
                f"AI extraction is limited to {MAX_EXTRACT_IMAGE_COUNT} screenshots per upload "
                f"to keep the server stable. Please split this game into smaller batches or enter it manually."
            )
        return (
            f"AI extraction is limited to {MAX_EXTRACT_IMAGE_COUNT} screenshots per upload "
            f"to keep the server stable. Please upload fewer screenshots at a time."
        )
    if any(_file_size(path) > MAX_EXTRACT_IMAGE_BYTES for path in paths):
        return (
            f"One or more screenshots are too large for AI extraction "
            f"(max {_format_mb(MAX_EXTRACT_IMAGE_BYTES)} each). Try cropping or compressing the image, "
            "or fill in the game manually below."
        )
    total_bytes = sum(_file_size(path) for path in paths)
    if total_bytes > MAX_EXTRACT_TOTAL_BYTES:
        return (
            f"These screenshots total {_format_mb(total_bytes)}, which is above the "
            f"{_format_mb(MAX_EXTRACT_TOTAL_BYTES)} AI extraction limit. Please split them into smaller uploads "
            "or fill in the game manually below."
        )
    return None


def _rows_for_template(rows: list) -> list:
    """Convert parsed rows to template-friendly dicts (Decimal -> str for form values).
    Net is derived from buyin/cashout/final_stack when missing: (cashout + final_stack) - buyin.
    Row values may be strings (e.g. from LLM extraction), so we coerce when deriving net.
    """
    out = []
    for r in rows:
        net = r.get("net_change")
        if net is None or (isinstance(net, str) and net.strip() == ""):
            bi, co, st = r.get("buyin"), r.get("cashout"), r.get("final_stack")
            if bi is not None or co is not None or st is not None:
                net = _to_decimal(co) + _to_decimal(st) - _to_decimal(bi)
        def _str_val(key: str) -> str:
            v = r.get(key)
            if v is None or v == "":
                return ""
            return str(v)
        out.append({
            "player_id": r.get("player_id") or "",
            "raw_name": r.get("raw_name") or "",
            "buyin": _str_val("buyin"),
            "cashout": _str_val("cashout"),
            "final_stack": _str_val("final_stack"),
            "net_change": str(net) if net is not None and not (isinstance(net, str) and (net or "").strip() == "") else "",
            "errors": r.get("errors", []),
        })
    return out


def _game_totals_key(total_buyins: Decimal, total_cashouts: Decimal, sum_net: Decimal) -> tuple:
    """Normalized key for duplicate detection (round to 2 decimals)."""
    return (
        round(float(total_buyins), 2),
        round(float(total_cashouts), 2),
        round(float(sum_net), 2),
    )


# ---- List ----
@router.get("", response_class=HTMLResponse)
async def game_list(request: Request, flash: str = ""):
    if not require_admin(request):
        return _redirect_login()
    flash_message = flash.replace("+", " ") if flash else None
    flash_type = "success" if flash_message else None
    with Session(engine) as session:
        games = list(session.exec(select(Game).order_by(Game.played_at.desc())).all())
        # Per-game: entry count, balanced, sum_net, total_buyins, total_cashouts
        game_list_data = []
        total_discrepancy = Decimal(0)
        totals_keys: list[tuple] = []
        for g in games:
            entries = list(session.exec(select(GameEntry).where(GameEntry.game_id == g.id)).all())
            total_net = sum(e.net_change for e in entries)
            total_buyins = sum((e.buyin or Decimal(0)) for e in entries)
            total_cashouts = sum((e.cashout or Decimal(0)) for e in entries)
            balanced = abs(total_net) <= BALANCE_EPSILON
            # Discrepancy sign: positive net = game lost value → show negative; negative net = game gained value → show positive
            game_discrepancy = -total_net
            total_discrepancy += game_discrepancy
            key = _game_totals_key(total_buyins, total_cashouts, total_net)
            totals_keys.append(key)
            paid_up = len(settlements_to_remove_for_game(session, g.id)) > 0
            game_list_data.append({
                "game": g,
                "entry_count": len(entries),
                "balanced": balanced,
                "sum_net": total_net,
                "discrepancy": game_discrepancy,
                "total_buyins": total_buyins,
                "total_cashouts": total_cashouts,
                "paid_up": paid_up,
            })
        # Flag games that share the same (buyins, cashouts, net) as another (potential duplicate)
        key_counts: dict[tuple, int] = {}
        for k in totals_keys:
            key_counts[k] = key_counts.get(k, 0) + 1
        for i, item in enumerate(game_list_data):
            key = _game_totals_key(item["total_buyins"], item["total_cashouts"], item["sum_net"])
            item["possible_duplicate"] = key_counts.get(key, 0) > 1
    return templates.TemplateResponse(
        "game_list.html",
        {
            "request": request,
            "game_list_data": game_list_data,
            "total_discrepancy": total_discrepancy,
            "flash_message": flash_message,
            "flash_type": flash_type,
        },
    )


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
    """
    Step 1 → Step 2 (review). Handles three use cases:
    - Single game: one screenshot (or notes only) → one extraction, one game in games[].
    - Single game, multiple screenshots: grouping=one_game → one extraction with all images, one game with comma-separated image URLs.
    - Multiple games: multiple screenshots, grouping=per_screenshot → one extraction per image, N games in games[].
    No files and no notes → one empty game (manual entry on review).
    """
    if not require_admin(request):
        return _redirect_login()
    import uuid
    try:
        # Allow 10 MB per file and many files (multiple screenshots = multiple games)
        form = await request.form(
            max_part_size=MAX_UPLOAD_SIZE_BYTES,
            max_files=MAX_UPLOAD_FILES,
        )
    except Exception as e:
        logger.exception("Add game: invalid form data: %s", e)
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
    saved_original_filenames = []  # user's filename (e.g. IMG_2025-02-15.jpg) for LLM date inference
    source_image_path_or_url = None
    upload_size_error = False
    upload_save_error = False  # e.g. disk full, permission denied
    for file in files:
        if not hasattr(file, "filename") or not file.filename:
            continue
        original_filename = (file.filename or "").strip()
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
        except OSError as e:
            logger.warning("Add game: could not save upload %s: %s", original_filename, e)
            upload_save_error = True
            continue
        except Exception as e:
            logger.warning("Add game: could not save upload %s: %s", original_filename, e, exc_info=True)
            upload_save_error = True
            continue
        saved_paths.append(path)
        saved_original_filenames.append(original_filename)
        if source_image_path_or_url is None:
            source_image_path_or_url = f"/uploads/{name}"

    # Load players first so we can pass them to the LLM for player matching and use them when resolving suggestions
    try:
        with Session(engine) as session:
            players = get_active_players(session)
    except Exception as e:
        logger.exception("Add game: database error loading players: %s", e)
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

    def _extract_rows(extracted, name_to_id):
        out = []
        for r in extracted:
            player_id = ""
            suggested = r.get("suggested_player_name")
            if suggested and name_to_id:
                pid = name_to_id.get(normalize_name(suggested))
                if pid:
                    player_id = pid
            out.append({
                "player_id": player_id,
                "raw_name": r.get("raw_name", "") or "",
                "buyin": r.get("buyin", "") or "",
                "cashout": r.get("cashout", "") or "",
                "final_stack": r.get("final_stack", "") or "",
                "net_change": r.get("net_change", "") or "",
                "errors": [],
            })
        return out

    name_to_id = {normalize_name(p.name): p.id for p in players}
    player_names = [p.name for p in players]
    games_for_review: list[dict] = []
    screenshot_grouping = (form.get("screenshot_grouping") or "").strip() or "per_screenshot"
    # Use env at request time so updated OPENAI_API_KEY is picked up after redeploy
    openai_key_set = bool((os.getenv("OPENAI_API_KEY") or "").strip() or OPENAI_API_KEY)
    extraction_limit_error = _extraction_limit_error(saved_paths, screenshot_grouping)
    should_run_extraction = openai_key_set and (notes or saved_paths) and not extraction_limit_error

    if should_run_extraction:
        logger.info("Add game: running OpenAI extraction (notes=%s, saved_paths=%d)", bool(notes), len(saved_paths))
        # Notes only (no screenshots): always one game from notes, regardless of "one game per screenshot" setting
        if notes and not saved_paths:
            rows = [_blank_review_row()]
            result = None
            try:
                result = extract_game(
                    notes=notes,
                    image_paths=None,
                    image_display_names=None,
                    player_names=player_names,
                    alias_map=PLAYER_ALIASES or {},
                )
                extracted = result.get("rows") or []
                if extracted:
                    rows = _extract_rows(extracted, name_to_id)
                if not played_at and result and result.get("suggested_played_at"):
                    try:
                        from datetime import date as date_type
                        d = date_type.fromisoformat(result["suggested_played_at"])
                        played_at = datetime.combine(d, datetime.min.time())
                        played_at_str = result["suggested_played_at"]
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                logger.warning("Add game: extraction failed (notes only): %s", e, exc_info=True)
            sum_net = sum((_row_net(r) for r in rows), Decimal(0))
            game_date_iso = played_at_str or (result.get("suggested_played_at") if result else "") or ""
            games_for_review.append({
                "source_image_path_or_url": "",
                "rows": _rows_for_template(rows),
                "sum_net": sum_net,
                "balanced": abs(sum_net) <= BALANCE_EPSILON,
                "extracted_from_screenshot": bool(rows and (rows[0].get("raw_name") or rows[0].get("net_change"))),
                "played_at_iso": game_date_iso,
            })
        elif len(saved_paths) > 1 and screenshot_grouping == "one_game":
            # All screenshots = one game: single extraction with all images
            all_urls = [f"/uploads/{p.name}" for p in saved_paths]
            source_image_path_or_url_combined = ",".join(all_urls)
            rows = [_blank_review_row()]
            result = None
            try:
                result = extract_game(
                    notes=notes or None,
                    image_paths=saved_paths,
                    image_display_names=saved_original_filenames,
                    player_names=player_names,
                    alias_map=PLAYER_ALIASES or {},
                )
                extracted = result.get("rows") or []
                if extracted:
                    rows = _extract_rows(extracted, name_to_id)
                if not played_at and result and result.get("suggested_played_at"):
                    try:
                        from datetime import date as date_type
                        d = date_type.fromisoformat(result["suggested_played_at"])
                        played_at = datetime.combine(d, datetime.min.time())
                        played_at_str = result["suggested_played_at"]
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                logger.warning("Add game: extraction failed (one_game mode): %s", e, exc_info=True)
            sum_net = sum((_row_net(r) for r in rows), Decimal(0))
            game_date_iso = played_at_str or (result.get("suggested_played_at") if result else "") or ""
            games_for_review.append({
                "source_image_path_or_url": source_image_path_or_url_combined,
                "rows": _rows_for_template(rows),
                "sum_net": sum_net,
                "balanced": abs(sum_net) <= BALANCE_EPSILON,
                "extracted_from_screenshot": bool(rows and (rows[0].get("raw_name") or rows[0].get("net_change"))),
                "played_at_iso": game_date_iso,
            })
        elif len(saved_paths) > 1:
            # One game per screenshot
            for idx, path in enumerate(saved_paths):
                name = path.name
                url = f"/uploads/{name}"
                display_name = saved_original_filenames[idx] if idx < len(saved_original_filenames) else None
                result = None
                try:
                    result = extract_game(
                        image_paths=[path],
                        image_display_names=[display_name] if display_name else None,
                        player_names=player_names,
                        alias_map=PLAYER_ALIASES or {},
                    )
                    extracted = result.get("rows") or []
                    rows = _extract_rows(extracted, name_to_id) if extracted else []
                except Exception as e:
                    logger.warning("Add game: extraction failed for screenshot %s: %s", name, e, exc_info=True)
                    rows = []
                if not rows:
                    rows = [_blank_review_row()]
                sum_net = sum((_row_net(r) for r in rows), Decimal(0))
                game_date_iso = (result.get("suggested_played_at") if result else "") or played_at_str or ""
                games_for_review.append({
                    "source_image_path_or_url": url,
                    "rows": _rows_for_template(rows),
                    "sum_net": sum_net,
                    "balanced": abs(sum_net) <= BALANCE_EPSILON,
                    "extracted_from_screenshot": bool(rows and (rows[0].get("raw_name") or rows[0].get("net_change"))),
                    "played_at_iso": game_date_iso,
                })
        else:
            rows = [_blank_review_row()]
            result = None
            try:
                result = extract_game(
                    notes=notes or None,
                    image_paths=saved_paths or None,
                    image_display_names=saved_original_filenames if saved_paths else None,
                    player_names=player_names,
                    alias_map=PLAYER_ALIASES or {},
                )
                extracted = result.get("rows") or []
                if extracted:
                    rows = _extract_rows(extracted, name_to_id)
                if not played_at and result and result.get("suggested_played_at"):
                    try:
                        from datetime import date as date_type
                        d = date_type.fromisoformat(result["suggested_played_at"])
                        played_at = datetime.combine(d, datetime.min.time())
                        played_at_str = result["suggested_played_at"]
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                logger.warning("Add game: extraction failed (single screenshot/notes): %s", e, exc_info=True)
            sum_net = sum((_row_net(r) for r in rows), Decimal(0))
            game_date_iso = played_at_str or (result.get("suggested_played_at") if result else "") or ""
            games_for_review.append({
                "source_image_path_or_url": source_image_path_or_url or "",
                "rows": _rows_for_template(rows),
                "sum_net": sum_net,
                "balanced": abs(sum_net) <= BALANCE_EPSILON,
                "extracted_from_screenshot": bool(rows and (rows[0].get("raw_name") or rows[0].get("net_change"))),
                "played_at_iso": game_date_iso,
            })
    else:
        # No API key, extraction disabled, or no notes/files: fall back to manual review
        if len(saved_paths) > 1 and screenshot_grouping == "one_game":
            all_urls = [f"/uploads/{p.name}" for p in saved_paths]
            games_for_review.append({
                "source_image_path_or_url": ",".join(all_urls),
                "rows": _rows_for_template([_blank_review_row()]),
                "sum_net": Decimal(0),
                "balanced": True,
                "extracted_from_screenshot": False,
                "played_at_iso": played_at_str or "",
            })
        elif len(saved_paths) > 1:
            for path in saved_paths:
                games_for_review.append({
                    "source_image_path_or_url": f"/uploads/{path.name}",
                    "rows": _rows_for_template([_blank_review_row()]),
                    "sum_net": Decimal(0),
                    "balanced": True,
                    "extracted_from_screenshot": False,
                    "played_at_iso": played_at_str or "",
                })
        else:
            games_for_review.append({
                "source_image_path_or_url": source_image_path_or_url or "",
                "rows": _rows_for_template([_blank_review_row()]),
                "sum_net": Decimal(0),
                "balanced": True,
                "extracted_from_screenshot": False,
                "played_at_iso": played_at_str or "",
            })

    errors_list = []
    if (notes or saved_paths) and not openai_key_set:
        errors_list.append("OPENAI_API_KEY is not set. AI extraction from notes/screenshots is disabled. Set it in your environment to use it, or fill in the game manually below.")
    if extraction_limit_error:
        errors_list.append(extraction_limit_error)
    if (notes or saved_paths) and should_run_extraction and games_for_review:
        last_game = games_for_review[-1]
        rows_for_last = last_game.get("rows") or []
        has_any_filled = any(
            (r.get("raw_name") or "").strip() or (r.get("net_change") or "").strip()
            for r in rows_for_last
        )
        if not has_any_filled:
            if notes and not saved_paths:
                errors_list.append("Could not extract player rows from your notes. You can fill in the game manually below.")
            elif saved_paths and not notes:
                errors_list.append("Could not extract from your screenshot(s)—they may not have loaded or the format wasn't recognized. You can fill in the game manually below.")
            else:
                errors_list.append("Could not extract player rows from your notes or screenshot(s). You can fill in the game manually below.")
    if upload_size_error:
        errors_list.append("Some files were too large (max 10 MB per file) and were skipped.")
    if upload_save_error:
        errors_list.append("Some files could not be saved (e.g. disk full or permission issue). Try fewer/smaller files or check server storage.")
    try:
        return templates.TemplateResponse(
            "game_review.html",
            {
                "request": request,
                "played_at": played_at,
                "played_at_iso": played_at.strftime("%Y-%m-%d") if played_at else "",
                "games": games_for_review,
                "game_id": None,
                "players": players,
                "errors": errors_list,
                "force_save": False,
                "force_reason": "",
            },
        )
    except Exception as e:
        logger.exception("Add game: failed to render review page: %s", e)
        return templates.TemplateResponse(
            "game_new.html",
            {
                "request": request,
                "prefill_date": played_at_str or "",
                "flash_message": f"Something went wrong. Please try again. ({type(e).__name__}: {e})",
                "flash_type": "error",
            },
        )


# ---- Review: POST with full grid -> validate; re-render or show confirm ----
def _form_has_multi_game(form_dict: dict) -> bool:
    return any(k.startswith("games[0]") for k in (form_dict or {}).keys())

@router.post("/review", response_class=HTMLResponse)
async def review_post(request: Request):
    if not require_admin(request):
        return _redirect_login()
    try:
        form = await request.form()
        fd = _form_dict(form)
    except Exception as e:
        logger.exception("Review: invalid form: %s", e)
        return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
    with Session(engine) as session:
        players = get_active_players(session)
    if _form_has_multi_game(fd):
        try:
            data = parse_multi_game_form(fd)
        except Exception as e:
            logger.exception("Review: parse multi-game form failed: %s", e)
            return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
        with Session(engine) as session:
            for g in data["games"]:
                _resolve_new_players(session, g["rows"])
            session.commit()
            players = get_active_players(session)
        if data["errors"]:
            games_for_review = [
                {
                    "source_image_path_or_url": g["source_image_path_or_url"] or "",
                    "rows": _rows_for_template(g["rows"]),
                    "sum_net": g["sum_net"],
                    "balanced": g["balanced"],
                    "extracted_from_screenshot": False,
                    "played_at_iso": g["played_at"].strftime("%Y-%m-%d") if g.get("played_at") else "",
                }
                for g in data["games"]
            ]
            return templates.TemplateResponse(
                "game_review.html",
                {
                    "request": request,
                    "played_at": data["played_at"],
                    "played_at_iso": data["played_at"].strftime("%Y-%m-%d") if data["played_at"] else "",
                    "games": games_for_review,
                    "game_id": None,
                    "players": players,
                    "errors": data["errors"],
                    "force_save": fd.get("force_save") in ("1", "on", "true", "yes"),
                    "force_reason": (fd.get("force_reason") or "").strip() or "",
                    "edit_mode": False,
                },
            )
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
    try:
        data = parse_game_form(fd)
    except Exception as e:
        logger.exception("Review: parse game form failed: %s", e)
        return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
    with Session(engine) as session:
        _resolve_new_players(session, data["rows"])
        session.commit()
        players = get_active_players(session)
    if data["errors"]:
        return templates.TemplateResponse(
            "game_review.html",
            {
                "request": request,
                "played_at": data["played_at"],
                "played_at_iso": data["played_at"].strftime("%Y-%m-%d") if data["played_at"] else "",
                "games": [{
                    "source_image_path_or_url": data["source_image_path_or_url"] or "",
                    "rows": _rows_for_template(data["rows"]),
                    "sum_net": data["sum_net"],
                    "balanced": data["balanced"],
                    "extracted_from_screenshot": False,
                }],
                "game_id": None,
                "players": players,
                "errors": data["errors"],
                "force_save": data["force_save"],
                "force_reason": data["force_reason"] or "",
                "edit_mode": False,
            },
        )
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
        fd = _form_dict(form)
    except Exception as e:
        logger.exception("Save game: invalid form: %s", e)
        return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
    if _form_has_multi_game(fd):
        try:
            data = parse_multi_game_form(fd)
        except Exception as e:
            logger.exception("Save game: parse multi-game form failed: %s", e)
            return RedirectResponse(url="/games/new?flash=Invalid+form.+Please+try+again.", status_code=302)
        if data["errors"]:
            with Session(engine) as session:
                players = get_active_players(session)
            games_for_review = [
                {
                    "source_image_path_or_url": g["source_image_path_or_url"] or "",
                    "rows": _rows_for_template(g["rows"]),
                    "sum_net": g["sum_net"],
                    "balanced": g["balanced"],
                    "extracted_from_screenshot": False,
                    "played_at_iso": g["played_at"].strftime("%Y-%m-%d") if g.get("played_at") else "",
                }
                for g in data["games"]
            ]
            return templates.TemplateResponse(
                "game_review.html",
                {
                    "request": request,
                    "played_at": data["played_at"],
                    "played_at_iso": data["played_at"].strftime("%Y-%m-%d") if data["played_at"] else "",
                    "games": games_for_review,
                    "game_id": None,
                    "players": players,
                    "errors": data["errors"],
                    "force_save": fd.get("force_save") in ("1", "on", "true", "yes"),
                    "force_reason": (fd.get("force_reason") or "").strip() or "",
                    "edit_mode": False,
                },
            )
        any_unbalanced = any(not g["balanced"] for g in data["games"])
        force_save = fd.get("force_save") in ("1", "on", "true", "yes")
        force_reason = (fd.get("force_reason") or "").strip()
        if any_unbalanced and not (force_save and force_reason):
            with Session(engine) as session:
                players = get_active_players(session)
            player_names = {p.id: p.name for p in players}
            return templates.TemplateResponse(
                "game_confirm.html",
                {
                    "request": request,
                    "parsed": data,
                    "players": players,
                    "player_names": player_names,
                    "game_id": None,
                    "confirm_error": "Please provide a reason for the discrepancy to save.",
                },
            )
        paid_up = fd.get("paid_up") in ("1", "on", "true", "yes")
        if paid_up:
            redir = check_payment_unlocked_redirect(request, next_url="/games/new")
            if redir:
                return redir
        try:
            with Session(engine) as session:
                for g in data["games"]:
                    _resolve_new_players(session, g["rows"])
                for g in data["games"]:
                    game = Game(
                        played_at=g["played_at"],
                        source_image_path_or_url=g["source_image_path_or_url"],
                    )
                    session.add(game)
                    session.flush()
                    # One GameEntry per row; same player can have multiple rows — all are stored and summed for that player
                    for r in g["rows"]:
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
                    if paid_up:
                        settled_at = g["played_at"].date() if g.get("played_at") else date.today()
                        for r in g["rows"]:
                            if r.get("player_id") and r.get("net_change") is not None:
                                session.add(
                                    Settlement(
                                        player_id=r["player_id"],
                                        game_id=game.id,
                                        settled_at=settled_at,
                                        amount=r["net_change"],
                                        note="Paid up at game save",
                                    )
                                )
                session.commit()
        except Exception as e:
            logger.exception("Save game: failed to save %d game(s) to database: %s", len(data["games"]), e)
            return RedirectResponse(url="/games/new?flash=Save+failed.+Please+try+again.", status_code=302)
        n_games = len(data["games"])
        redirect_url = f"/games/saved?n={n_games}"
        if add_another and data["played_at"]:
            redirect_url = f"/games/new?date={data['played_at'].strftime('%Y-%m-%d')}&flash=Games+saved"
        return RedirectResponse(url=redirect_url, status_code=302)
    try:
        data = parse_game_form(fd)
    except Exception as e:
        logger.exception("Save game: parse game form failed: %s", e)
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
                "games": [{
                    "source_image_path_or_url": data["source_image_path_or_url"] or "",
                    "rows": _rows_for_template(data["rows"]),
                    "sum_net": data["sum_net"],
                    "balanced": data["balanced"],
                    "extracted_from_screenshot": False,
                }],
                "game_id": None,
                "players": players,
                "errors": data["errors"],
                "force_save": data["force_save"],
                "force_reason": data["force_reason"] or "",
                "edit_mode": False,
            },
        )
    if not data["balanced"] and not (data["force_save"] and (data["force_reason"] or "").strip()):
        with Session(engine) as session:
            players = get_active_players(session)
        player_names = {p.id: p.name for p in players}
        return templates.TemplateResponse(
            "game_confirm.html",
            {
                "request": request,
                "parsed": data,
                "players": players,
                "player_names": player_names,
                "game_id": None,
                "confirm_error": "Please provide a reason for the discrepancy to save.",
            },
        )
    paid_up = fd.get("paid_up") in ("1", "on", "true", "yes")
    if paid_up:
        redir = check_payment_unlocked_redirect(request, next_url="/games/new")
        if redir:
            return redir
    try:
        with Session(engine) as session:
            _resolve_new_players(session, data["rows"])
            game = Game(
                played_at=data["played_at"],
                source_image_path_or_url=data["source_image_path_or_url"],
            )
            session.add(game)
            session.flush()
            # One GameEntry per row; same player can have multiple rows — all are stored and summed for that player
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
            if paid_up:
                settled_at = data["played_at"].date() if data.get("played_at") else date.today()
                for r in data["rows"]:
                    if r.get("player_id") and r.get("net_change") is not None:
                        session.add(
                            Settlement(
                                player_id=r["player_id"],
                                game_id=game.id,
                                settled_at=settled_at,
                                amount=r["net_change"],
                                note="Paid up at game save",
                            )
                        )
            session.commit()
    except Exception as e:
        logger.exception("Save game: failed to save game to database: %s", e)
        return RedirectResponse(url="/games/new?flash=Save+failed.+Please+try+again.", status_code=302)
    redirect_url = "/games/saved?n=1"
    if add_another and data["played_at"]:
        redirect_url = f"/games/new?date={data['played_at'].strftime('%Y-%m-%d')}&flash=Game+saved"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---- Success landing (after save) ----
@router.get("/saved", response_class=HTMLResponse)
async def game_saved_page(request: Request, n: str = "1"):
    if not require_admin(request):
        return _redirect_login()
    try:
        count = max(1, int(n))
    except ValueError:
        count = 1
    message = "Game added successfully." if count == 1 else f"{count} games added successfully."
    response = templates.TemplateResponse(
        "game_saved.html",
        {"request": request, "message": message, "count": count},
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@router.post("/mark-all-paid-up", response_class=HTMLResponse)
async def mark_all_games_paid_up_post(request: Request):
    """Create settlements for every game that is not yet paid up, so all game nets are settled (nothing in outstanding from games). You can then mark specific games as unpaid to add those nets back."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request, next_url="/games")
    if redir:
        return redir
    with Session(engine) as session:
        games = list(session.exec(select(Game).order_by(Game.played_at)).all())
        created = 0
        for game in games:
            if settlements_to_remove_for_game(session, game.id):
                continue
            entries = list(session.exec(select(GameEntry).where(GameEntry.game_id == game.id)).all())
            settled_at = game.played_at.date() if game.played_at else date.today()
            for e in entries:
                if e.net_change is not None:
                    session.add(
                        Settlement(
                            player_id=e.player_id,
                            game_id=game.id,
                            settled_at=settled_at,
                            amount=e.net_change,
                            note="Paid up",
                        )
                    )
                    created += 1
        session.commit()
    return RedirectResponse(url="/games?flash=All+games+marked+as+paid+up.+Mark+individual+games+as+unpaid+to+add+nets+back+to+outstanding.", status_code=302)


# ---- Delete game (confirm + do) ----
@router.get("/{game_id}/delete", response_class=HTMLResponse)
async def game_delete_confirm(request: Request, game_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        game = session.get(Game, game_id)
        if not game:
            return RedirectResponse(url="/games", status_code=302)
        entries = list(session.exec(select(GameEntry).where(GameEntry.game_id == game_id)).all())
        entry_count = len(entries)
        sum_net = sum(e.net_change for e in entries)
        played_at_str = game.played_at.strftime("%Y-%m-%d") if game.played_at else "—"
    return templates.TemplateResponse(
        "game_delete_confirm.html",
        {
            "request": request,
            "game_id": game_id,
            "played_at_str": played_at_str,
            "entry_count": entry_count,
            "sum_net": sum_net,
        },
    )


@router.post("/{game_id}/delete", response_class=HTMLResponse)
async def game_delete_post(request: Request, game_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        game = session.get(Game, game_id)
        if not game:
            return RedirectResponse(url="/games", status_code=302)
        for entry in session.exec(select(GameEntry).where(GameEntry.game_id == game_id)).all():
            session.delete(entry)
        session.delete(game)
        session.commit()
    return RedirectResponse(url="/games?flash=Game+deleted.", status_code=302)


@router.post("/{game_id}/mark-not-paid-up", response_class=HTMLResponse)
async def game_mark_not_paid_up_post(request: Request, game_id: str):
    """Remove settlements for this game (linked by game_id or legacy match). Outstanding is only unpaid games + expenses; so this game becomes unpaid and each player's outstanding gains that game's net."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request, next_url=f"/games/{game_id}")
    if redir:
        return redir
    with Session(engine) as session:
        game = session.get(Game, game_id)
        if not game:
            return RedirectResponse(url="/games", status_code=302)
        to_delete = settlements_to_remove_for_game(session, game_id)
        if not to_delete:
            return RedirectResponse(url="/games?flash=Game+already+unpaid+(no+payments+to+remove).", status_code=302)
        for s in to_delete:
            session.delete(s)
        session.commit()
    return RedirectResponse(url="/games?flash=Game+marked+as+unpaid.+Net+amounts+added+back+to+each+player%27s+outstanding.", status_code=302)


@router.post("/{game_id}/mark-paid-up", response_class=HTMLResponse)
async def game_mark_paid_up_post(request: Request, game_id: str):
    """Record settlements for this game so it is marked paid up (balances no longer outstanding)."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request, next_url=f"/games/{game_id}")
    if redir:
        return redir
    with Session(engine) as session:
        game = session.get(Game, game_id)
        if not game:
            return RedirectResponse(url="/games", status_code=302)
        if settlements_to_remove_for_game(session, game_id):
            return RedirectResponse(url="/games?flash=Game+already+marked+as+paid+up.", status_code=302)
        entries = list(session.exec(select(GameEntry).where(GameEntry.game_id == game_id)).all())
        if not entries:
            return RedirectResponse(url="/games?flash=Game+has+no+entries.", status_code=302)
        settled_at = game.played_at.date() if game.played_at else date.today()
        for e in entries:
            if e.net_change is not None:
                session.add(
                    Settlement(
                        player_id=e.player_id,
                        game_id=game.id,
                        settled_at=settled_at,
                        amount=e.net_change,
                        note="Paid up",
                    )
                )
        session.commit()
    return RedirectResponse(url="/games?flash=Game+marked+as+paid+up.", status_code=302)


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
        paid_up = len(settlements_to_remove_for_game(session, game_id)) > 0
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
            "paid_up": paid_up,
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
        _resolve_new_players(session, data["rows"])
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
