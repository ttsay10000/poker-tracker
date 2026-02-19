"""Player analytics: core metrics, streaks, lineup-dependent stats, rivalry (best friend / nemesis)."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median, stdev
from typing import Optional

from sqlmodel import Session, col, func, select

from models import Game, GameEntry, Player


# ---- Filter helpers ----
def _game_query(session: Session, date_from: Optional[date], date_to: Optional[date], player_id: Optional[str] = None):
    """Games in date range, optionally only where player_id participated."""
    q = select(Game).order_by(Game.played_at)
    if date_from:
        q = q.where(col(Game.played_at) >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(col(Game.played_at) <= datetime.combine(date_to, datetime.max.time()))
    games = list(session.exec(q).all())
    if not games or not player_id:
        return games
    game_ids = [g.id for g in games]
    # Filter to games where this player has an entry
    entry_game_ids = set(
        session.exec(
            select(GameEntry.game_id).where(GameEntry.game_id.in_(game_ids)).where(GameEntry.player_id == player_id)
        ).all()
    )
    return [g for g in games if g.id in entry_game_ids]


def _entries_for_player(session: Session, player_id: str, game_ids: list[str]) -> list[GameEntry]:
    """GameEntry rows for player in given games."""
    if not game_ids:
        return []
    return list(
        session.exec(
            select(GameEntry).where(GameEntry.game_id.in_(game_ids)).where(GameEntry.player_id == player_id)
        ).all()
    )


def _player_ids_in_games(session: Session, game_ids: list[str]) -> list[str]:
    """Distinct player_ids that have at least one entry in these games."""
    if not game_ids:
        return []
    rows = session.exec(
        select(GameEntry.player_id).where(GameEntry.game_id.in_(game_ids)).distinct()
    ).all()
    return list(dict.fromkeys(rows))


# ---- Core metrics (single player, date-filtered) ----
def player_core_stats(
    session: Session,
    player_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> dict:
    """Core stats for one player over the filter window. Missing buyin/cashout excluded from those averages."""
    games = _game_query(session, date_from, date_to, player_id)
    if not games:
        return {
            "games_played": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "win_rate": None,
            "total_net": Decimal(0),
            "avg_net_per_game": None,
            "median_net_per_game": None,
            "best_game_net": None,
            "worst_game_net": None,
            "stddev_net_per_game": None,
            "avg_buyin": None,
            "avg_cashout": None,
            "avg_final_stack": None,
            "avg_roi_per_game": None,
            "avg_when_winning": None,
            "avg_when_losing": None,
        }
    game_ids = [g.id for g in games]
    entries = _entries_for_player(session, player_id, game_ids)
    by_game = {e.game_id: e for e in entries}
    nets = [by_game[g.id].net_change for g in games]
    wins = sum(1 for n in nets if n > 0)
    losses = sum(1 for n in nets if n < 0)
    pushes = sum(1 for n in nets if n == 0)
    games_played = len(nets)
    total_net = sum(nets)
    win_rate = (wins / games_played) if games_played else None
    avg_net = (total_net / games_played) if games_played else None
    nets_float = [float(n) for n in nets]
    median_net = Decimal(str(median(nets_float))) if nets_float else None
    best_net = max(nets) if nets else None
    worst_net = min(nets) if nets else None
    stddev_net = Decimal(str(stdev(nets_float))) if len(nets_float) > 1 else None

    buyins = [e.buyin for e in entries if e.buyin is not None and e.buyin > 0]
    cashouts = [e.cashout for e in entries if e.cashout is not None]
    final_stacks = [e.final_stack for e in entries if e.final_stack is not None]
    avg_buyin = (sum(buyins) / len(buyins)) if buyins else None
    avg_cashout = (sum(cashouts) / len(cashouts)) if cashouts else None
    avg_final_stack = (sum(final_stacks) / len(final_stacks)) if final_stacks else None

    roi_list = []
    for e in entries:
        if e.buyin is not None and e.buyin > 0 and e.net_change is not None:
            roi_list.append(float(e.net_change / e.buyin))
    avg_roi = Decimal(str(sum(roi_list) / len(roi_list))) if roi_list else None

    winning_nets = [n for n in nets if n > 0]
    losing_nets = [n for n in nets if n < 0]
    avg_when_winning = (sum(winning_nets) / len(winning_nets)) if winning_nets else None
    avg_when_losing = (sum(losing_nets) / len(losing_nets)) if losing_nets else None

    return {
        "games_played": games_played,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "total_net": total_net,
        "avg_net_per_game": avg_net,
        "median_net_per_game": median_net,
        "best_game_net": best_net,
        "worst_game_net": worst_net,
        "stddev_net_per_game": stddev_net,
        "avg_buyin": avg_buyin,
        "avg_cashout": avg_cashout,
        "avg_final_stack": avg_final_stack,
        "avg_roi_per_game": avg_roi,
        "avg_when_winning": avg_when_winning,
        "avg_when_losing": avg_when_losing,
    }


# ---- Streaks (pushes break streak) ----
def player_streaks(
    session: Session,
    player_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> dict:
    """Ordered by played_at; pushes break streak."""
    games = _game_query(session, date_from, date_to, player_id)
    if not games:
        return {
            "current_streak_type": None,
            "current_streak_len": 0,
            "longest_win_streak": 0,
            "longest_loss_streak": 0,
        }
    game_ids = [g.id for g in games]
    entries = _entries_for_player(session, player_id, game_ids)
    by_game = {e.game_id: e for e in entries}
    # nets in chronological order
    nets = [by_game[g.id].net_change for g in games]
    current_type = None
    current_len = 0
    longest_win = 0
    longest_loss = 0
    run_win = 0
    run_loss = 0
    for n in nets:
        if n > 0:
            run_win += 1
            run_loss = 0
            longest_win = max(longest_win, run_win)
        elif n < 0:
            run_loss += 1
            run_win = 0
            longest_loss = max(longest_loss, run_loss)
        else:
            run_win = 0
            run_loss = 0
    # Current streak = last run
    for n in reversed(nets):
        if n > 0:
            if current_type == "L":
                break
            current_type = "W"
            current_len += 1
        elif n < 0:
            if current_type == "W":
                break
            current_type = "L"
            current_len += 1
        else:
            break
    return {
        "current_streak_type": current_type,
        "current_streak_len": current_len,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
    }


# ---- Cumulative net for one player (chart) ----
def chart_data_single_player(
    session: Session,
    player_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> dict:
    """Cumulative net over time for this player. X=played_at, Y=cumulative net."""
    games = _game_query(session, date_from, date_to, player_id)
    if not games:
        return {"labels": [], "data": []}
    game_ids = [g.id for g in games]
    entries = _entries_for_player(session, player_id, game_ids)
    by_game = {e.game_id: e.net_change for e in entries}
    labels = [g.played_at.strftime("%Y-%m-%d") for g in games]
    running = Decimal(0)
    data = []
    for g in games:
        running += by_game.get(g.id, Decimal(0))
        data.append(float(running))
    return {"labels": labels, "data": data}


# ---- All games for player (chronological: most recent first) ----
def recent_games_for_player(
    session: Session,
    player_id: str,
    limit: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[dict]:
    """Games for this player with date, net_change, buyin, cashout, lineup size. Most recent first. limit=None = all."""
    games = _game_query(session, date_from, date_to, player_id)
    games = list(reversed(games))  # most recent first
    if limit is not None:
        games = games[:limit]
    if not games:
        return []
    game_ids = [g.id for g in games]
    entries = _entries_for_player(session, player_id, game_ids)
    by_game = {e.game_id: e for e in entries}
    # Lineup size per game
    counts = {}
    for gid in game_ids:
        c = session.exec(select(func.count(GameEntry.id)).where(GameEntry.game_id == gid)).one()
        counts[gid] = c or 0
    out = []
    for g in games:
        e = by_game.get(g.id)
        if not e:
            continue
        out.append({
            "game_id": g.id,
            "played_at": g.played_at,
            "net_change": e.net_change,
            "buyin": e.buyin,
            "cashout": e.cashout,
            "final_stack": e.final_stack,
            "lineup_size": counts.get(g.id, 0),
        })
    return out


# ---- Lineup-dependent "With X" stats ----
def lineup_with_x_stats(
    session: Session,
    focal_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
    min_sample: int = 5,
) -> list[dict]:
    """For focal A, for each other player X with games_with_X >= min_sample: with/without stats and deltas."""
    games = _game_query(session, date_from, date_to, focal_id)
    if not games:
        return []
    game_ids = [g.id for g in games]
    # All entries in these games (focal + others)
    all_entries = list(session.exec(
        select(GameEntry).where(GameEntry.game_id.in_(game_ids))
    ).all())
    focal_entries_by_game = {e.game_id: e for e in all_entries if e.player_id == focal_id}
    other_player_ids = list(dict.fromkeys(e.player_id for e in all_entries if e.player_id != focal_id))
    player_names = {p.id: p.name for p in session.exec(select(Player).where(Player.id.in_(other_player_ids))).all()}

    rows = []
    for x_id in other_player_ids:
        games_with_x = []
        games_without_x = []
        for g in games:
            if g.id not in focal_entries_by_game:
                continue
            fe = focal_entries_by_game[g.id]
            x_in_game = any(e.player_id == x_id for e in all_entries if e.game_id == g.id)
            if x_in_game:
                games_with_x.append(fe.net_change)
            else:
                games_without_x.append(fe.net_change)
        games_with_x_n = len(games_with_x)
        if games_with_x_n < min_sample:
            continue
        total_with = sum(games_with_x)
        win_rate_with = (sum(1 for n in games_with_x if n > 0) / games_with_x_n) if games_with_x_n else None
        avg_with = (total_with / games_with_x_n) if games_with_x_n else None

        games_without_n = len(games_without_x)
        if games_without_n == 0:
            rows.append({
                "player_id": x_id,
                "player_name": player_names.get(x_id, x_id),
                "games_with_x": games_with_x_n,
                "win_rate_with_x": win_rate_with,
                "avg_net_with_x": avg_with,
                "total_net_with_x": total_with,
                "games_without_x": 0,
                "win_rate_without_x": None,
                "avg_net_without_x": None,
                "win_rate_delta": None,
                "avg_net_delta": None,
                "no_baseline": True,
            })
            continue
        total_without = sum(games_without_x)
        win_rate_without = sum(1 for n in games_without_x if n > 0) / games_without_n
        avg_without = total_without / games_without_n
        wr_delta = (win_rate_with - win_rate_without) if win_rate_with is not None else None
        avg_delta = (avg_with - avg_without) if (avg_with is not None and avg_without is not None) else None
        rows.append({
            "player_id": x_id,
            "player_name": player_names.get(x_id, x_id),
            "games_with_x": games_with_x_n,
            "win_rate_with_x": win_rate_with,
            "avg_net_with_x": avg_with,
            "total_net_with_x": total_with,
            "games_without_x": games_without_n,
            "win_rate_without_x": win_rate_without,
            "avg_net_without_x": avg_without,
            "win_rate_delta": wr_delta,
            "avg_net_delta": avg_delta,
            "no_baseline": False,
        })
    return rows


def _best_friend_nemesis_for_window(
    session: Session,
    focal_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
    min_sample: int,
) -> tuple[Optional[dict], Optional[dict]]:
    """Best friend = max avg_net_delta, Nemesis = min avg_net_delta. Tiebreaker: games_with_X then name."""
    rows = lineup_with_x_stats(session, focal_id, date_from, date_to, min_sample)
    # Exclude no_baseline for BF/N selection
    eligible = [r for r in rows if not r.get("no_baseline") and r.get("avg_net_delta") is not None]
    if not eligible:
        return None, None
    best = max(eligible, key=lambda r: (r["avg_net_delta"], r["games_with_x"], r["player_name"]))
    nemesis = min(eligible, key=lambda r: (r["avg_net_delta"], -r["games_with_x"], r["player_name"]))
    return (
        {"player_name": best["player_name"], "player_id": best["player_id"], "avg_net_delta": best["avg_net_delta"], "games_with_x": best["games_with_x"]},
        {"player_name": nemesis["player_name"], "player_id": nemesis["player_id"], "avg_net_delta": nemesis["avg_net_delta"], "games_with_x": nemesis["games_with_x"]},
    )


def rivalry_badges_windows(
    session: Session,
    focal_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
    min_sample: int = 5,
) -> dict:
    """Best Friend / Nemesis for: all-time (use filter), last 90d, last 12mo. Windows use their own date range."""
    today = date.today()
    windows = {
        "all_time": (date_from, date_to),
        "last_90_days": (today - timedelta(days=90), today),
        "last_12_months": (today - timedelta(days=365), today),
    }
    result = {}
    for key, (d_from, d_to) in windows.items():
        bf, nem = _best_friend_nemesis_for_window(session, focal_id, d_from, d_to, min_sample)
        result[key] = {"best_friend": bf, "nemesis": nem}
    return result


# ---- Monthly bucketing: best friend / nemesis per month, then counts ----
def _monthly_best_friend_nemesis(
    session: Session,
    focal_id: str,
    year_month: str,
    min_sample_month: int = 2,
) -> tuple[Optional[str], Optional[str]]:
    """For month YYYY-MM, who is A's best friend and nemesis (by avg_net_delta). Returns (bf_player_id, nemesis_player_id)."""
    y, m = int(year_month[:4]), int(year_month[5:7])
    d_start = date(y, m, 1)
    if m == 12:
        d_end = date(y, 12, 31)
    else:
        d_end = date(y, m + 1, 1) - timedelta(days=1)
    rows = lineup_with_x_stats(session, focal_id, d_start, d_end, min_sample_month)
    eligible = [r for r in rows if not r.get("no_baseline") and r.get("avg_net_delta") is not None]
    if not eligible:
        return None, None
    best = max(eligible, key=lambda r: (r["avg_net_delta"], r["games_with_x"], r["player_name"]))
    nem = min(eligible, key=lambda r: (r["avg_net_delta"], -r["games_with_x"], r["player_name"]))
    return best["player_id"], nem["player_id"]


def rivalry_monthly_counts(
    session: Session,
    focal_id: str,
    min_games_in_month: int = 2,
    min_sample_month: int = 2,
) -> list[dict]:
    """Months where A played >= min_games_in_month; for each other X: # months best friend, # months nemesis, months_together."""
    # All games for focal
    all_games = _game_query(session, None, None, focal_id)
    if not all_games:
        return []
    months_with_focal: set[str] = set()
    games_by_month: dict[str, list] = defaultdict(list)
    for g in all_games:
        ym = g.played_at.strftime("%Y-%m")
        months_with_focal.add(ym)
        games_by_month[ym].append(g)
    eligible_months = [ym for ym in months_with_focal if len(games_by_month[ym]) >= min_games_in_month]
    if not eligible_months:
        return []

    bf_count: dict[str, int] = defaultdict(int)
    nemesis_count: dict[str, int] = defaultdict(int)
    months_together: dict[str, int] = defaultdict(int)

    other_player_ids = set()
    for ym in eligible_months:
        bf_id, nem_id = _monthly_best_friend_nemesis(session, focal_id, ym, min_sample_month)
        if bf_id:
            bf_count[bf_id] += 1
            other_player_ids.add(bf_id)
        if nem_id:
            nemesis_count[nem_id] += 1
            other_player_ids.add(nem_id)
        # months_together: months where focal and X both played
        games_that_month = games_by_month[ym]
        game_ids = [g.id for g in games_that_month]
        all_entries = list(session.exec(select(GameEntry).where(GameEntry.game_id.in_(game_ids))).all())
        for e in all_entries:
            if e.player_id != focal_id:
                other_player_ids.add(e.player_id)
                months_together[e.player_id] += 1
    # Actually months_together should be count of months where both played. Recompute.
    months_together = defaultdict(int)
    for ym in eligible_months:
        games_that_month = games_by_month[ym]
        game_ids = [g.id for g in games_that_month]
        all_entries = list(session.exec(select(GameEntry).where(GameEntry.game_id.in_(game_ids))).all())
        players_that_month = set(e.player_id for e in all_entries)
        for x_id in players_that_month:
            if x_id != focal_id:
                months_together[x_id] += 1

    # All-time avg_net_delta for each X (for display)
    with_x_all = lineup_with_x_stats(session, focal_id, None, None, 1)
    with_x_by_id = {r["player_id"]: r for r in with_x_all}

    player_names = {p.id: p.name for p in session.exec(select(Player).where(Player.id.in_(other_player_ids))).all()}
    rows = []
    for x_id in other_player_ids:
        r = with_x_by_id.get(x_id, {})
        rows.append({
            "player_id": x_id,
            "player_name": player_names.get(x_id, x_id),
            "best_friend_months": bf_count[x_id],
            "nemesis_months": nemesis_count[x_id],
            "months_together": months_together[x_id],
            "all_time_avg_net_delta": r.get("avg_net_delta"),
            "all_time_games_with_x": r.get("games_with_x", 0),
        })
    return rows


def most_frequent_best_friend_nemesis(
    session: Session,
    focal_id: str,
    min_games_in_month: int = 2,
    min_sample_month: int = 2,
) -> dict:
    """Most Frequent Best Friend and Nemesis (by monthly count). Tiebreaker: months_together, then avg_net_delta, then name."""
    rows = rivalry_monthly_counts(session, focal_id, min_games_in_month, min_sample_month)
    if not rows:
        return {"most_frequent_best_friend": None, "most_frequent_nemesis": None}
    bf_row = max(rows, key=lambda r: (r["best_friend_months"], r["months_together"], (r["all_time_avg_net_delta"] or Decimal(-10**9)), r["player_name"]))
    # Nemesis: more months = worse; tiebreaker: more months_together, then lower avg_net_delta (worse), then name
    nem_row = max(rows, key=lambda r: (r["nemesis_months"], r["months_together"], -(float(r["all_time_avg_net_delta"]) if r["all_time_avg_net_delta"] is not None else -10**9), r["player_name"]))
    mf_bf = bf_row if bf_row["best_friend_months"] > 0 else None
    mf_nem = nem_row if nem_row["nemesis_months"] > 0 else None
    return {
        "most_frequent_best_friend": {"player_name": mf_bf["player_name"], "player_id": mf_bf["player_id"], "months": mf_bf["best_friend_months"]} if mf_bf else None,
        "most_frequent_nemesis": {"player_name": mf_nem["player_name"], "player_id": mf_nem["player_id"], "months": mf_nem["nemesis_months"]} if mf_nem else None,
    }


# ---- Leaderboard (all players, filtered) ----
def get_players_for_stats(session: Session, include_inactive: bool = False) -> list[Player]:
    if include_inactive:
        return list(session.exec(select(Player).order_by(Player.name)).all())
    return list(session.exec(select(Player).where(Player.is_active == True).order_by(Player.name)).all())


def leaderboard_rows(
    session: Session,
    date_from: Optional[date],
    date_to: Optional[date],
    include_inactive: bool = False,
    min_games: int = 1,
) -> list[dict]:
    """One row per player: total_net, games_played, win_rate, avg_net_per_game, avg_buyin, outstanding (from services)."""
    from services import outstanding
    players = get_players_for_stats(session, include_inactive)
    rows = []
    for p in players:
        core = player_core_stats(session, p.id, date_from, date_to)
        if core["games_played"] < min_games:
            continue
        rows.append({
            "player": p,
            "total_net": core["total_net"],
            "games_played": core["games_played"],
            "win_rate": core["win_rate"],
            "avg_net_per_game": core["avg_net_per_game"],
            "avg_buyin": core["avg_buyin"],
            "outstanding": outstanding(session, p.id),
        })
    return rows
