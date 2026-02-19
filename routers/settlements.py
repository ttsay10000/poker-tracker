"""Record settlement (payment). amount > 0 = organizer paid player; < 0 = player paid organizer."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auth import require_admin
from config import BASE_DIR
from database import engine
from models import Settlement
from services import get_active_players, get_player_by_id, outstanding

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


@router.get("/record", response_class=HTMLResponse)
async def record_page(request: Request, player_id: str = ""):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        players = get_active_players(session)
    return templates.TemplateResponse(
        "settlement_record.html",
        {"request": request, "players": players, "preselect_player_id": player_id, "today_iso": date.today().isoformat()},
    )


@router.post("/record")
async def record_post(request: Request):
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    player_id = (form.get("player_id") or "").strip()
    amount_str = (form.get("amount") or "0").strip().replace(",", "")
    direction = form.get("direction", "i_paid_player")  # i_paid_player => +amount, player_paid_me => -amount
    date_str = form.get("settled_at") or ""
    note = (form.get("note") or "").strip() or None
    try:
        amount = Decimal(amount_str)
    except Exception:
        return RedirectResponse(url="/settlements/record?error=invalid_amount", status_code=302)
    if direction == "player_paid_me":
        amount = -amount
    if amount == 0:
        return RedirectResponse(url="/settlements/record?error=zero_amount", status_code=302)
    settled_at = date.today()
    if date_str:
        try:
            settled_at = date.fromisoformat(date_str)
        except ValueError:
            pass
    with Session(engine) as session:
        if not get_player_by_id(session, player_id):
            return RedirectResponse(url="/settlements/record?error=player_required", status_code=302)
        s = Settlement(player_id=player_id, settled_at=settled_at, amount=amount, note=note)
        session.add(s)
        session.commit()
    return RedirectResponse(url="/dashboard?flash=Settlement+recorded", status_code=302)


@router.post("/settled-up")
async def settled_up_post(request: Request):
    """Record a single settlement that zeroes out the player's outstanding balance."""
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    player_id = (form.get("player_id") or "").strip()
    if not player_id:
        return RedirectResponse(url="/dashboard?flash=Player+required", status_code=302)
    with Session(engine) as session:
        if not get_player_by_id(session, player_id):
            return RedirectResponse(url="/dashboard?flash=Player+not+found", status_code=302)
        out = outstanding(session, player_id)
        if out == 0:
            return RedirectResponse(url="/dashboard?flash=Already+settled", status_code=302)
        # Settlement amount = outstanding (positive = we paid them, negative = they paid us)
        s = Settlement(player_id=player_id, settled_at=date.today(), amount=out, note="Settled up")
        session.add(s)
        session.commit()
    return RedirectResponse(url="/dashboard?flash=Settled+up", status_code=302)


@router.post("/settled-up-all")
async def settled_up_all_post(request: Request):
    """Record settlements that zero out every player's outstanding balance."""
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        players = get_active_players(session)
        settled_count = 0
        for p in players:
            out = outstanding(session, p.id)
            if out == 0:
                continue
            s = Settlement(player_id=p.id, settled_at=date.today(), amount=out, note="Settled up")
            session.add(s)
            settled_count += 1
        if settled_count:
            session.commit()
    if settled_count == 0:
        return RedirectResponse(url="/dashboard?flash=Everyone+already+settled", status_code=302)
    msg = "All+players+settled+up" if settled_count > 1 else "Settled+up"
    return RedirectResponse(url=f"/dashboard?flash={msg}", status_code=302)


@router.get("/record-batch", response_class=HTMLResponse)
async def record_batch_page(request: Request):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        players = get_active_players(session)
    return templates.TemplateResponse(
        "settlement_record_batch.html",
        {"request": request, "players": players, "today_iso": date.today().isoformat()},
    )


@router.post("/record-batch")
async def record_batch_post(request: Request):
    """Record multiple payments in one submit. Form: player_id[], amount[], direction[], note[]; single settled_at."""
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    date_str = form.get("settled_at") or ""
    settled_at = date.today()
    if date_str:
        try:
            settled_at = date.fromisoformat(date_str)
        except ValueError:
            pass

    # Support multiple rows: player_id_1, amount_1, direction_1, note_1, etc. or arrays
    player_ids = form.getlist("player_id") or []
    amounts = form.getlist("amount") or []
    directions = form.getlist("direction") or []
    notes = form.getlist("note") or []

    created = 0
    errors = []
    with Session(engine) as session:
        for i in range(max(len(player_ids), len(amounts))):
            player_id = (player_ids[i] if i < len(player_ids) else "").strip()
            amount_str = (amounts[i] if i < len(amounts) else "0").strip().replace(",", "")
            direction = directions[i] if i < len(directions) else "i_paid_player"
            note = (notes[i] if i < len(notes) else "").strip() or None
            if not player_id:
                continue
            try:
                amount = Decimal(amount_str)
            except Exception:
                errors.append(f"Row {i + 1}: invalid amount")
                continue
            if direction == "player_paid_me":
                amount = -amount
            if amount == 0:
                continue
            if not get_player_by_id(session, player_id):
                errors.append(f"Row {i + 1}: player not found")
                continue
            s = Settlement(player_id=player_id, settled_at=settled_at, amount=amount, note=note)
            session.add(s)
            created += 1
        if created:
            session.commit()
    if errors:
        return RedirectResponse(url="/settlements/record-batch?error=batch_errors", status_code=302)
    if created == 0:
        return RedirectResponse(url="/settlements/record-batch?error=no_payments", status_code=302)
    flash_msg = "Settlements+recorded" if created > 1 else "Settlement+recorded"
    return RedirectResponse(url=f"/dashboard?flash={flash_msg}", status_code=302)
