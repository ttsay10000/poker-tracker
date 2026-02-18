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
from services import get_active_players, get_player_by_id

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
