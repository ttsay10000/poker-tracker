"""Extract poker game data from screenshots and/or notes using OpenAI."""
import json
import base64
import logging
import os
from pathlib import Path
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from config import (
    MAX_EXTRACT_IMAGE_BYTES,
    MAX_EXTRACT_IMAGE_COUNT,
    MAX_EXTRACT_TOTAL_BYTES,
    OPENAI_API_KEY,
    OPENAI_REQUEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

# No game-count or storage limits: extraction runs whenever notes or screenshots are provided.
# Form limits: max 50 files, 10 MB per file (see routers/games.py and config.py).

_EXTRACT_PROMPT_BASE = """Extract poker game results into a single JSON object with two fields:

1) suggested_played_at: If the game date is visible in the image(s), text, or in the file name(s) (e.g. "Poker 4/1" or "4/1" = April 1 → use 2025-04-01 or the appropriate year; 2025-02-15, 20250215), set this to YYYY-MM-DD. If not visible or unclear, set to null.

2) players: An array of player rows. For each row return:
- raw_name: the name as shown (e.g. from the app or list)
- buyin: number only (e.g. 20 or 20.00)
- cashout: number only (buy-out / cashout)
- final_stack: number if visible, else empty string
- net_change: net profit/loss as a number (negative if loss; drop the leading + for profits, e.g. +41.25 → 41.25)

If the notes use the format "Name — buyin | cashout | +net or -net" (em dash, pipe-separated), parse each line into one player row with raw_name, buyin, cashout, and net_change."""

_EXTRACT_PROMPT_SUFFIX_NO_HINTS = """

Respond with a single JSON object only, no other text. Example:
{"suggested_played_at":"2025-02-15","players":[{"raw_name":"Alice","buyin":"20","cashout":"45","final_stack":"","net_change":"25"},{"raw_name":"Bob","buyin":"20","cashout":"0","final_stack":"","net_change":"-20"}]}
If date is not visible: {"suggested_played_at":null,"players":[...]}"""


def _player_hints_prompt(player_names: List[str], alias_map: Dict[str, str]) -> str:
    """Build prompt text asking the LLM to suggest a player when it can match raw_name to the database or aliases."""
    if not player_names and not alias_map:
        return _EXTRACT_PROMPT_SUFFIX_NO_HINTS
    lines = [
        "",
        "Player matching: Try to assign each row to a known player when possible.",
        "Known players (use one of these exact names for suggested_player_name when you match): " + ", ".join(sorted(player_names)) if player_names else "",
        "Common aliases (raw_name -> canonical name): " + ", ".join(f"{k} -> {v}" for k, v in sorted(alias_map.items())) if alias_map else "",
        "For each row: if you can match raw_name to a known player or alias, add suggested_player_name with the exact canonical name from the known players list. If unsure or no match, omit suggested_player_name; still provide raw_name as the starting point. On error or ambiguity, do not assign suggested_player_name.",
        "",
        "Respond with a single JSON object: suggested_played_at (date or null) and players (array). Example:",
        '{"suggested_played_at":"2025-02-15","players":[{"raw_name":"nik","buyin":"20","cashout":"45","final_stack":"","net_change":"25","suggested_player_name":"Nick Pham"},{"raw_name":"Unknown","buyin":"20","cashout":"0","final_stack":"","net_change":"-20"}]',
    ]
    return "\n".join(l for l in lines if l is not None and len(l) > 0)


def _encode_image(path: Path) -> Tuple[str, str]:
    with open(path, "rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode("utf-8")
    ext = path.suffix.lower()
    media_type = "image/png"
    if ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".gif":
        media_type = "image/gif"
    elif ext == ".webp":
        media_type = "image/webp"
    return media_type, b64


def _parse_amount(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().replace(",", "").replace("$", "").lstrip("+")
    try:
        Decimal(s)
        return s
    except Exception:
        return ""


def _parse_date_str(s: Any) -> Optional[str]:
    """Return YYYY-MM-DD if valid, else None."""
    if s is None or (isinstance(s, str) and not s.strip()):
        return None
    s = str(s).strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            from datetime import datetime
            datetime.strptime(s, "%Y-%m-%d")
            return s
        except ValueError:
            pass
    return None


def _parse_response(text: str) -> Dict[str, Any]:
    """Parse LLM response. Returns {"rows": [...], "suggested_played_at": "YYYY-MM-DD" or None}."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"rows": [], "suggested_played_at": None}
    suggested_played_at = None
    items: List[dict] = []
    if isinstance(data, dict):
        suggested_played_at = _parse_date_str(data.get("suggested_played_at"))
        items = data.get("players") or data.get("rows") or []
    if isinstance(data, list):
        items = data
    if not isinstance(items, list):
        return {"rows": [], "suggested_played_at": suggested_played_at}
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = {
            "raw_name": (item.get("raw_name") or "").strip() or "",
            "buyin": _parse_amount(item.get("buyin")),
            "cashout": _parse_amount(item.get("cashout")),
            "final_stack": _parse_amount(item.get("final_stack")),
            "net_change": _parse_amount(item.get("net_change")),
        }
        suggested = (item.get("suggested_player_name") or "").strip() or None
        if suggested:
            row["suggested_player_name"] = suggested
        rows.append(row)
    return {"rows": rows, "suggested_played_at": suggested_played_at}


def _image_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def extract_game(
    notes: Optional[str] = None,
    image_paths: Optional[List[Path]] = None,
    image_display_names: Optional[List[str]] = None,
    player_names: Optional[List[str]] = None,
    alias_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Extract game date and player rows from notes and/or images using OpenAI.
    Returns {"rows": list of row dicts, "suggested_played_at": "YYYY-MM-DD" or None}.
    Row dicts have raw_name, buyin, cashout, final_stack, net_change, and optionally suggested_player_name.
    image_display_names: if provided, one per image_path; used in the prompt so the LLM can infer date from
    the user's original filename/title (e.g. "IMG_2025-02-15.jpg") instead of the saved UUID filename.
    """
    empty_result: Dict[str, Any] = {"rows": [], "suggested_played_at": None}
    # Prefer env at call time so updated keys (e.g. after redeploy) are used without restart
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or OPENAI_API_KEY or ""
    if not api_key:
        logger.info("OpenAI extraction skipped: OPENAI_API_KEY not set (check env or .env)")
        return empty_result
    notes = (notes or "").strip()
    image_paths = image_paths or []
    image_display_names = image_display_names or []
    if not notes and not image_paths:
        logger.debug("OpenAI extraction skipped: no notes and no image_paths")
        return empty_result
    valid_paths = [p for p in image_paths if p and getattr(p, "is_file", lambda: False)() and p.is_file()]
    if not notes and not valid_paths:
        logger.warning(
            "OpenAI extraction skipped: no notes and no valid image files (got %s paths; files may be missing or not saved)",
            len(image_paths),
        )
        return empty_result
    if len(valid_paths) > MAX_EXTRACT_IMAGE_COUNT:
        logger.warning(
            "OpenAI extraction skipped: too many images (%d > %d)",
            len(valid_paths),
            MAX_EXTRACT_IMAGE_COUNT,
        )
        return empty_result
    if any(_image_size(path) > MAX_EXTRACT_IMAGE_BYTES for path in valid_paths):
        logger.warning(
            "OpenAI extraction skipped: one or more images exceed %d bytes",
            MAX_EXTRACT_IMAGE_BYTES,
        )
        return empty_result
    total_image_bytes = sum(_image_size(path) for path in valid_paths)
    if total_image_bytes > MAX_EXTRACT_TOTAL_BYTES:
        logger.warning(
            "OpenAI extraction skipped: total image payload too large (%d > %d bytes)",
            total_image_bytes,
            MAX_EXTRACT_TOTAL_BYTES,
        )
        return empty_result

    prompt_suffix = _player_hints_prompt(player_names or [], alias_map or {})
    extract_prompt = _EXTRACT_PROMPT_BASE + prompt_suffix

    # Use original filenames (e.g. "IMG_2025-02-15.jpg") when provided so the LLM can infer date from the title
    file_names_context = ""
    if valid_paths:
        names = []
        for i, p in enumerate(valid_paths):
            if i < len(image_display_names) and (image_display_names[i] or "").strip():
                names.append((image_display_names[i] or "").strip())
            else:
                names.append(p.name)
        file_names_context = "File names (titles) of the image(s)—use these to infer the game date when a date appears in the filename (e.g. 2025-02-15, 20250215, or in text like 'Feb 18'): " + ", ".join(names) + "\n\n"

    content: list[dict] = []
    if notes:
        content.append({
            "type": "text",
            "text": file_names_context + "Pasted notes:\n\n" + notes + "\n\n" + extract_prompt,
        })
    for path in valid_paths:
        media_type, b64 = _encode_image(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64}"},
        })
    if not content:
        return empty_result
    # If we only had images, prepend the prompt (with file names so LLM can use them for date)
    if content and content[0].get("type") != "text":
        content.insert(0, {"type": "text", "text": file_names_context + extract_prompt})

    try:
        from openai import OpenAI
        logger.info(
            "OpenAI extraction: calling API (notes=%s, image_count=%d, total_image_bytes=%d)",
            bool(notes),
            len(valid_paths),
            total_image_bytes,
        )
        client = OpenAI(api_key=api_key, timeout=OPENAI_REQUEST_TIMEOUT_SECONDS)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
        )
        text = (response.choices[0].message.content or "").strip()
        parsed = _parse_response(text)
        logger.info("OpenAI extraction: got %d rows", len(parsed.get("rows") or []))
        return parsed
    except Exception as e:
        logger.warning("OpenAI extraction failed: %s", e, exc_info=True)
        return empty_result


def extract_game_from_image(image_path: Path) -> Dict[str, Any]:
    """Single-image convenience; use extract_game(..., image_paths=[path]) for multi-image."""
    return extract_game(image_paths=[image_path])
