"""Aggregates and business logic."""
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session, col, func, select
from sqlmodel.sql.expression import Select

from config import BALANCE_EPSILON
from models import Expense, Game, GameEntry, Player, Settlement


def settlements_for_game(session: Session, game_id: str) -> list[Settlement]:
    """Settlements linked to this game (e.g. from 'Paid up at game save')."""
    return list(session.exec(select(Settlement).where(Settlement.game_id == game_id)).all())


def normalize_name(name: str) -> str:
    return (name or "").strip().lower()


# ---- Players ----
def get_active_players(session: Session):
    return session.exec(select(Player).where(Player.is_active == True).order_by(Player.name)).all()


def get_player_by_id(session: Session, player_id: str) -> Optional[Player]:
    return session.get(Player, player_id)


def get_player_by_name_normalized(session: Session, name_normalized: str) -> Optional[Player]:
    return session.exec(select(Player).where(Player.name_normalized == name_normalized)).first()


# ---- Lifetime / settled / outstanding ----
def lifetime_net(session: Session, player_id: str) -> Decimal:
    r = session.exec(
        select(func.coalesce(func.sum(GameEntry.net_change), 0)).where(GameEntry.player_id == player_id)
    ).one()
    return Decimal(str(r))


def settled_net(session: Session, player_id: str) -> Decimal:
    r = session.exec(
        select(func.coalesce(func.sum(Settlement.amount), 0)).where(Settlement.player_id == player_id)
    ).one()
    return Decimal(str(r))


def expense_total(session: Session, player_id: str) -> Decimal:
    """Sum of non-game charges for this player (positive = they owe). Excludes soft-deleted."""
    r = session.exec(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.player_id == player_id)
        .where(Expense.deleted_at.is_(None))
    ).one()
    return Decimal(str(r))


def outstanding(session: Session, player_id: str) -> Decimal:
    """Lifetime net from games − expenses (charges) − settlements. Positive = organizer owes player; negative = player owes organizer. Game stats use only lifetime_net from games."""
    return lifetime_net(session, player_id) - expense_total(session, player_id) - settled_net(session, player_id)


def get_expense_groups_for_finances(session: Session) -> list[dict[str, Any]]:
    """List expense groups (from Add charge) and ungrouped single expenses for the finances page. Most recent first. Excludes soft-deleted."""
    all_expenses = list(
        session.exec(select(Expense).where(Expense.deleted_at.is_(None)).order_by(Expense.created_at.desc())).all()
    )
    player_ids = {e.player_id for e in all_expenses}
    players = {p.id: p for p in session.exec(select(Player).where(Player.id.in_(player_ids))).all()} if player_ids else {}

    groups: dict[str, dict[str, Any]] = {}
    single_expenses: list[dict[str, Any]] = []

    for e in all_expenses:
        if e.expense_group_id:
            g = groups.get(e.expense_group_id)
            if not g:
                g = {
                    "expense_group_id": e.expense_group_id,
                    "note": e.note or "",
                    "amount_per_player": e.amount,
                    "total": Decimal(0),
                    "player_count": 0,
                    "player_names": [],
                    "created_at": e.created_at,
                }
                groups[e.expense_group_id] = g
            g["total"] += e.amount
            g["player_count"] += 1
            g["player_names"].append(players.get(e.player_id).name if players.get(e.player_id) else e.player_id)
            if e.created_at and (not g.get("created_at") or e.created_at > g["created_at"]):
                g["created_at"] = e.created_at
        else:
            single_expenses.append({
                "id": e.id,
                "note": e.note or "",
                "amount": e.amount,
                "player_name": players.get(e.player_id).name if players.get(e.player_id) else e.player_id,
                "player_id": e.player_id,
                "created_at": e.created_at,
            })

    out = []
    for g in groups.values():
        out.append({"kind": "group", **g})
    for s in single_expenses:
        out.append({"kind": "single", **s})
    out.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    return out


def get_deleted_expense_groups_for_finances(session: Session) -> list[dict[str, Any]]:
    """List soft-deleted expense groups and single expenses for the finances page (Restore = add back to outstanding)."""
    all_expenses = list(
        session.exec(select(Expense).where(Expense.deleted_at.isnot(None)).order_by(Expense.deleted_at.desc())).all()
    )
    if not all_expenses:
        return []
    player_ids = {e.player_id for e in all_expenses}
    players = {p.id: p for p in session.exec(select(Player).where(Player.id.in_(player_ids))).all()} if player_ids else {}

    groups: dict[str, dict[str, Any]] = {}
    single_expenses: list[dict[str, Any]] = []

    for e in all_expenses:
        if e.expense_group_id:
            g = groups.get(e.expense_group_id)
            if not g:
                g = {
                    "expense_group_id": e.expense_group_id,
                    "note": e.note or "",
                    "amount_per_player": e.amount,
                    "total": Decimal(0),
                    "player_count": 0,
                    "player_names": [],
                    "created_at": e.created_at,
                    "deleted_at": e.deleted_at,
                }
                groups[e.expense_group_id] = g
            g["total"] += e.amount
            g["player_count"] += 1
            g["player_names"].append(players.get(e.player_id).name if players.get(e.player_id) else e.player_id)
            if e.deleted_at and (not g.get("deleted_at") or e.deleted_at > g.get("deleted_at")):
                g["deleted_at"] = e.deleted_at
        else:
            single_expenses.append({
                "id": e.id,
                "note": e.note or "",
                "amount": e.amount,
                "player_name": players.get(e.player_id).name if players.get(e.player_id) else e.player_id,
                "player_id": e.player_id,
                "created_at": e.created_at,
                "deleted_at": e.deleted_at,
            })

    out = []
    for g in groups.values():
        out.append({"kind": "group", **g})
    for s in single_expenses:
        out.append({"kind": "single", **s})
    out.sort(key=lambda x: x.get("deleted_at") or datetime.min, reverse=True)
    return out


def games_played_count(session: Session, player_id: str) -> int:
    return session.exec(select(func.count(GameEntry.id)).where(GameEntry.player_id == player_id)).one() or 0


def per_game_nets(session: Session, player_id: str) -> list[Decimal]:
    """Return list of net_change per game for this player (one value per game played)."""
    rows = session.exec(
        select(GameEntry.net_change).where(GameEntry.player_id == player_id)
    ).all()
    return list(rows) if rows else []


def per_game_net_stddev(session: Session, player_id: str) -> Optional[float]:
    """Standard deviation of per-game net for this player. None if fewer than 2 games."""
    nets = per_game_nets(session, player_id)
    if len(nets) < 2:
        return None
    vals = [float(n) for n in nets]
    n = len(vals)
    mean = sum(vals) / n
    variance = sum((x - mean) ** 2 for x in vals) / n
    return math.sqrt(variance)


# ---- Game date range (for default chart window) ----
def get_game_date_range(session: Session) -> tuple[Optional[date], Optional[date]]:
    """Return (min played_at date, max played_at date) across all games, or (None, None) if no games."""
    try:
        row = session.exec(
            select(func.min(Game.played_at), func.max(Game.played_at))
        ).one()
    except Exception:
        return (None, None)
    if not row or row[0] is None:
        return (None, None)
    min_dt, max_dt = row
    return (min_dt.date() if min_dt else None, max_dt.date() if max_dt else None)


# ---- Chart: cumulative net per player over time ----
def chart_data(session: Session, player_ids: list[str], date_from: Optional[date], date_to: Optional[date]):
    """Games sorted by played_at; cumulative totals per player. Carry forward on missing games."""
    q = select(Game).order_by(Game.played_at)
    if date_from:
        q = q.where(col(Game.played_at) >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(col(Game.played_at) <= datetime.combine(date_to, datetime.max.time()))
    games = list(session.exec(q).all())
    if not games:
        return {"labels": [], "datasets": []}

    # Build cumulative per player: for each game, sum net_change for that player in that game and add to running total
    labels = [g.played_at.strftime("%Y-%m-%d") for g in games]
    game_ids = [g.id for g in games]

    # Get all entries for these games and these players
    entries = session.exec(
        select(GameEntry)
        .where(GameEntry.game_id.in_(game_ids))
        .where(GameEntry.player_id.in_(player_ids) if player_ids else True)
    ).all()

    by_game_player: dict[tuple[str, str], Decimal] = {}
    for e in entries:
        by_game_player[(e.game_id, e.player_id)] = e.net_change

    players_in_scope = player_ids or [p.id for p in get_active_players(session)]
    # Cumulative: for each player, for each game in order, add that game's net_change to running total
    cumulative: dict[str, list[float]] = {pid: [] for pid in players_in_scope}
    running: dict[str, Decimal] = {pid: Decimal(0) for pid in players_in_scope}

    for g in games:
        for pid in players_in_scope:
            inc = by_game_player.get((g.id, pid), Decimal(0))
            running[pid] += inc
            cumulative[pid].append(float(running[pid]))
    # Player names for legend
    player_map = {p.id: p.name for p in session.exec(select(Player).where(Player.id.in_(players_in_scope))).all()}
    datasets = [
        {"label": player_map.get(pid, pid), "data": cumulative[pid]}
        for pid in players_in_scope
    ]
    return {"labels": labels, "datasets": datasets}


# ---- Settlements ----
def has_any_settlements(session: Session) -> bool:
    return session.exec(select(func.count(Settlement.id))).one() > 0


def settlements_affect_players(session: Session, player_ids: list[str]) -> bool:
    if not player_ids: return False
    return session.exec(select(func.count(Settlement.id)).where(Settlement.player_id.in_(player_ids))).one() > 0
