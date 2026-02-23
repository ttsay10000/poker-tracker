"""Record settlement (payment). amount > 0 = organizer paid player; < 0 = player paid organizer."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import require_admin, check_payment_unlocked_redirect, set_payment_unlock_cookie
from config import BASE_DIR, PAYMENT_PASSWORD
from database import engine
from models import Expense, Player, Settlement
from services import get_active_players, get_deleted_expense_groups_for_finances, get_expense_groups_for_finances, get_player_by_id, outstanding
from templating import templates

router = APIRouter()


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


@router.post("/unlock")
async def unlock_post(request: Request):
    """Verify payment password and set unlock cookie."""
    if not require_admin(request):
        return _redirect_login()
    form = await request.form()
    password = (form.get("payment_password") or "").strip()
    next_url = (form.get("next") or request.query_params.get("next") or "").strip()
    if not next_url.startswith("/"):
        next_url = "/settlements"
    if password != PAYMENT_PASSWORD:
        return RedirectResponse(
            url="/settlements?unlock=1&error=invalid_password" + ("&next=" + next_url if next_url != "/settlements" else ""),
            status_code=302,
        )
    resp = RedirectResponse(url=next_url, status_code=302)
    set_payment_unlock_cookie(resp)
    return resp


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def finances_page(request: Request, player_id: str = "", unlock: str = "", next_param: str = ""):
    """Combined Finances page: record payments and add global charge."""
    if not require_admin(request):
        return _redirect_login()
    preselect = (request.query_params.get("player_id") or player_id or "").strip()
    flash_message = request.query_params.get("flash", "").replace("+", " ")
    show_unlock = unlock == "1"
    unlock_error = request.query_params.get("error") == "invalid_password"
    next_url = request.query_params.get("next") or next_param or ""
    with Session(engine) as session:
        players = get_active_players(session)
        expense_groups = get_expense_groups_for_finances(session)
        deleted_expense_groups = get_deleted_expense_groups_for_finances(session)
    return templates.TemplateResponse(
        "finances.html",
        {
            "request": request,
            "players": players,
            "preselect_player_id": preselect,
            "today_iso": date.today().isoformat(),
            "flash_message": flash_message or None,
            "flash_type": "success" if flash_message else None,
            "expense_groups": expense_groups,
            "deleted_expense_groups": deleted_expense_groups,
            "show_unlock": show_unlock,
            "unlock_error": unlock_error,
            "unlock_next": next_url,
        },
    )


@router.get("/record", response_class=HTMLResponse)
async def record_page(request: Request, player_id: str = ""):
    if not require_admin(request):
        return _redirect_login()
    url = "/settlements#record-payment"
    if player_id:
        url = f"/settlements?player_id={player_id}#record-payment"
    return RedirectResponse(url=url, status_code=302)


@router.get("/charge", response_class=HTMLResponse)
async def charge_page(request: Request):
    if not require_admin(request):
        return _redirect_login()
    return RedirectResponse(url="/settlements#add-charge", status_code=302)


@router.post("/charge")
async def charge_post(request: Request):
    """Create one expense per selected player (Harper crew or all)."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    form = await request.form()
    amount_str = (form.get("amount") or "0").strip().replace(",", "")
    note = (form.get("note") or "").strip() or None
    apply_to = (form.get("apply_to") or "all_players").strip()
    try:
        amount = Decimal(amount_str)
    except Exception:
        return RedirectResponse(url="/settlements?charge_error=invalid_amount#add-charge", status_code=302)
    if amount <= 0:
        return RedirectResponse(url="/settlements?charge_error=zero_amount#add-charge", status_code=302)
    group_id = str(uuid.uuid4())
    with Session(engine) as session:
        if apply_to == "harper_crew":
            players = list(session.exec(select(Player).where(Player.is_active == True).where(Player.harper_crew == True).order_by(Player.name)).all())
        else:
            players = get_active_players(session)
        if not players:
            return RedirectResponse(url="/settlements?charge_error=no_players#add-charge", status_code=302)
        for p in players:
            session.add(Expense(player_id=p.id, amount=amount, note=note, expense_group_id=group_id))
        session.commit()
    n = len(players)
    flash = f"Charge+recorded+for+{n}+player(s)"
    return RedirectResponse(url=f"/settlements?flash={flash}", status_code=302)


@router.post("/expense-group/{group_id}/delete")
async def delete_expense_group(request: Request, group_id: str):
    """Soft-delete all expenses in this group; removes that amount from outstanding. Restore adds back."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    with Session(engine) as session:
        expenses = list(session.exec(select(Expense).where(Expense.expense_group_id == group_id).where(Expense.deleted_at.is_(None))).all())
        now = datetime.utcnow()
        for e in expenses:
            e.deleted_at = now
            session.add(e)
        session.commit()
    return RedirectResponse(url="/settlements?flash=Charge+batch+deleted.+You+can+restore+it+below+to+add+back+to+outstanding.", status_code=302)


@router.post("/expense-group/{group_id}/restore")
async def restore_expense_group(request: Request, group_id: str):
    """Restore a soft-deleted expense group; adds those amounts back to outstanding."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    with Session(engine) as session:
        expenses = list(session.exec(select(Expense).where(Expense.expense_group_id == group_id).where(Expense.deleted_at.isnot(None))).all())
        if not expenses:
            return RedirectResponse(url="/settlements?flash=Nothing+to+restore+or+already+restored", status_code=302)
        for e in expenses:
            e.deleted_at = None
            session.add(e)
        session.commit()
    return RedirectResponse(url="/settlements?flash=Charge+batch+restored.+Added+back+to+outstanding.", status_code=302)


@router.post("/expense/{expense_id}/delete")
async def delete_expense(request: Request, expense_id: str):
    """Soft-delete a single expense; removes that amount from outstanding. Restore adds back."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    redirect_url = (request.query_params.get("next") or "").strip() or "/settlements"
    if not redirect_url.startswith("/"):
        redirect_url = "/settlements"
    with Session(engine) as session:
        expense = session.get(Expense, expense_id)
        if not expense:
            return RedirectResponse(url="/settlements?flash=Expense+not+found", status_code=302)
        expense.deleted_at = datetime.utcnow()
        session.add(expense)
        session.commit()
    sep = "&" if "?" in redirect_url else "?"
    return RedirectResponse(url=redirect_url + sep + "flash=Expense+deleted.+You+can+restore+it+below+to+add+back+to+outstanding.", status_code=302)


@router.post("/expense/{expense_id}/restore")
async def restore_expense(request: Request, expense_id: str):
    """Restore a soft-deleted expense; adds that amount back to outstanding."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    redirect_url = (request.query_params.get("next") or "").strip() or "/settlements"
    if not redirect_url.startswith("/"):
        redirect_url = "/settlements"
    with Session(engine) as session:
        expense = session.get(Expense, expense_id)
        if not expense:
            return RedirectResponse(url="/settlements?flash=Expense+not+found", status_code=302)
        if not expense.deleted_at:
            sep = "&" if "?" in redirect_url else "?"
            return RedirectResponse(url=redirect_url + sep + "flash=Expense+already+active", status_code=302)
        expense.deleted_at = None
        session.add(expense)
        session.commit()
    sep = "&" if "?" in redirect_url else "?"
    return RedirectResponse(url=redirect_url + sep + "flash=Expense+restored.+Added+back+to+outstanding.", status_code=302)


@router.get("/expense/{expense_id}/edit", response_class=HTMLResponse)
async def edit_expense_page(request: Request, expense_id: str):
    if not require_admin(request):
        return _redirect_login()
    with Session(engine) as session:
        expense = session.get(Expense, expense_id)
        if not expense:
            return RedirectResponse(url="/settlements?flash=Expense+not+found", status_code=302)
        if expense.deleted_at:
            return RedirectResponse(url="/settlements?flash=Expense+was+deleted.+Restore+it+below+to+edit.", status_code=302)
        player = get_player_by_id(session, expense.player_id)
    return templates.TemplateResponse(
        "expense_edit.html",
        {"request": request, "expense": expense, "player": player},
    )


@router.post("/expense/{expense_id}/edit")
async def edit_expense_post(request: Request, expense_id: str):
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    form = await request.form()
    amount_str = (form.get("amount") or "0").strip().replace(",", "")
    note = (form.get("note") or "").strip() or None
    try:
        amount = Decimal(amount_str)
    except Exception:
        return RedirectResponse(url=f"/settlements/expense/{expense_id}/edit?error=invalid_amount", status_code=302)
    if amount <= 0:
        return RedirectResponse(url=f"/settlements/expense/{expense_id}/edit?error=zero_amount", status_code=302)
    with Session(engine) as session:
        expense = session.get(Expense, expense_id)
        if not expense:
            return RedirectResponse(url="/settlements?flash=Expense+not+found", status_code=302)
        if expense.deleted_at:
            return RedirectResponse(url="/settlements?flash=Expense+was+deleted.+Restore+it+first.", status_code=302)
        expense.amount = amount
        expense.note = note
        session.add(expense)
        session.commit()
    next_url = (form.get("next") or "").strip() or "/settlements"
    if not next_url.startswith("/"):
        next_url = "/settlements"
    return RedirectResponse(url=next_url, status_code=302)


@router.post("/record")
async def record_post(request: Request):
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
    form = await request.form()
    player_id = (form.get("player_id") or "").strip()
    amount_str = (form.get("amount") or "0").strip().replace(",", "")
    direction = form.get("direction", "i_paid_player")  # i_paid_player => +amount, player_paid_me => -amount
    date_str = form.get("settled_at") or ""
    note = (form.get("note") or "").strip() or None
    try:
        amount = Decimal(amount_str)
    except Exception:
        return RedirectResponse(url="/settlements?error=invalid_amount#record-payment", status_code=302)
    if direction == "player_paid_me":
        amount = -amount
    if amount == 0:
        return RedirectResponse(url="/settlements?error=zero_amount#record-payment", status_code=302)
    settled_at = date.today()
    if date_str:
        try:
            settled_at = date.fromisoformat(date_str)
        except ValueError:
            pass
    with Session(engine) as session:
        if not get_player_by_id(session, player_id):
            return RedirectResponse(url="/settlements?error=player_required#record-payment", status_code=302)
        s = Settlement(player_id=player_id, settled_at=settled_at, amount=amount, note=note)
        session.add(s)
        session.commit()
    return RedirectResponse(url="/settlements?flash=Settlement+recorded", status_code=302)


@router.post("/settled-up")
async def settled_up_post(request: Request):
    """Record a single settlement that zeroes out the player's outstanding balance."""
    if not require_admin(request):
        return _redirect_login()
    redir = check_payment_unlocked_redirect(request)
    if redir:
        return redir
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
    redir = check_payment_unlocked_redirect(request, next_url="/dashboard")
    if redir:
        return redir
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
    redir = check_payment_unlocked_redirect(request, next_url="/settlements/record-batch")
    if redir:
        return redir
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
