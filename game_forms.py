"""Parse and validate game form data (review/confirm/save)."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from config import BALANCE_EPSILON


def _parse_decimal(s: Any) -> Optional[Decimal]:
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return None
    try:
        return Decimal(str(s).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(s: Any) -> Optional[datetime]:
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return None
    try:
        s = str(s).strip()
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        # date only
        from datetime import date
        d = date.fromisoformat(s)
        return datetime.combine(d, datetime.min.time())
    except (ValueError, TypeError):
        return None


def parse_row(row: dict, index: int) -> dict:
    """Parse one row from form. Returns dict with player_id, raw_name, buyin, cashout, final_stack, net_change, error."""
    player_id = (row.get("player_id") or "").strip() or None
    raw_name = (row.get("raw_name") or "").strip() or None
    buyin = _parse_decimal(row.get("buyin"))
    cashout = _parse_decimal(row.get("cashout"))
    final_stack = _parse_decimal(row.get("final_stack"))
    net_change = _parse_decimal(row.get("net_change"))

    err = []
    if not player_id:
        err.append("Select a player")
    if net_change is None and (buyin is not None or cashout is not None):
        net_change = (cashout or Decimal(0)) - (buyin or Decimal(0))
    if net_change is None:
        err.append("Net change required or provide buyin/cashout")
    if player_id and net_change is not None and buyin is not None and cashout is not None:
        computed = (cashout or Decimal(0)) - (buyin or Decimal(0))
        if abs((net_change or Decimal(0)) - computed) > BALANCE_EPSILON:
            err.append("Net doesn't match cashout - buyin")
    return {
        "player_id": player_id,
        "raw_name": raw_name,
        "buyin": buyin,
        "cashout": cashout,
        "final_stack": final_stack,
        "net_change": net_change,
        "errors": err,
    }


def parse_game_form(form_data: dict, row_prefix: str = "rows") -> dict:
    """
    form_data: flat dict from request.form() or from form with keys like played_at, rows[0][player_id], etc.
    Returns: {
        played_at: datetime | None,
        source_image_path_or_url: str | None,
        force_save: bool,
        force_reason: str | None,
        rows: list of parse_row results,
        sum_net: Decimal,
        delta: Decimal (same as sum_net for balance check),
        balanced: bool,
        errors: list str
    }
    """
    played_at = _parse_date(form_data.get("played_at"))
    source_image_path_or_url = (form_data.get("source_image_path_or_url") or "").strip() or None
    force_save = form_data.get("force_save") in ("1", "on", "true", "yes")
    force_reason = (form_data.get("force_reason") or "").strip() or None

    # Collect rows: form sends rows[0][player_id], rows[0][buyin], ...
    rows_raw: dict[int, dict] = {}
    prefix = row_prefix + "["
    for key, value in form_data.items():
        if not key.startswith(prefix) or "]" not in key:
            continue
        rest = key[len(prefix):]
        parts = rest.split("]", 1)
        try:
            idx = int(parts[0])
            field = parts[1].lstrip("[").rstrip("]") if len(parts) > 1 else ""
            if not field:
                continue
            if idx not in rows_raw:
                rows_raw[idx] = {}
            rows_raw[idx][field] = value
        except (ValueError, IndexError):
            continue

    indices = sorted(rows_raw.keys())
    rows = [parse_row(rows_raw[i], i) for i in indices]

    sum_net = sum((r["net_change"] or Decimal(0) for r in rows if r["net_change"] is not None), Decimal(0))
    balanced = abs(sum_net) <= BALANCE_EPSILON
    errors = []
    if not played_at:
        errors.append("Played at (date) is required")
    for i, r in enumerate(rows):
        if r["errors"]:
            errors.extend([f"Row {i+1}: {e}" for e in r["errors"]])
    if not balanced and not (force_save and force_reason):
        errors.append(f"Game does not balance (sum = {sum_net:.2f}). Use Force Save with a reason to override.")

    return {
        "played_at": played_at,
        "source_image_path_or_url": source_image_path_or_url,
        "force_save": force_save,
        "force_reason": force_reason,
        "rows": rows,
        "sum_net": sum_net,
        "delta": sum_net,
        "balanced": balanced,
        "errors": errors,
    }
