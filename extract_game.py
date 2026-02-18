"""Extract poker game data from screenshots and/or notes using OpenAI."""
import json
import base64
from pathlib import Path
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from config import OPENAI_API_KEY

_EXTRACT_PROMPT = """Extract poker game results into a list of players with amounts.
From the provided image(s) and/or text, find every player/row. For each row return:
- raw_name: the name as shown (e.g. from the app or list)
- buyin: number only (e.g. 20 or 20.00)
- cashout: number only (buy-out / cashout)
- final_stack: number if visible, else empty
- net_change: net profit/loss as a number (negative if loss)

Respond with a JSON array only, no other text. Example:
[{"raw_name":"Alice","buyin":"20","cashout":"45","final_stack":"","net_change":"25"},{"raw_name":"Bob","buyin":"20","cashout":"0","final_stack":"","net_change":"-20"}]"""


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
    s = str(val).strip().replace(",", "").replace("$", "")
    try:
        Decimal(s)
        return s
    except Exception:
        return ""


def _parse_response(text: str) -> List[Dict[str, str]]:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rows.append({
            "raw_name": (item.get("raw_name") or "").strip() or "",
            "buyin": _parse_amount(item.get("buyin")),
            "cashout": _parse_amount(item.get("cashout")),
            "final_stack": _parse_amount(item.get("final_stack")),
            "net_change": _parse_amount(item.get("net_change")),
        })
    return rows


def extract_game(notes: Optional[str] = None, image_paths: Optional[List[Path]] = None) -> List[Dict[str, str]]:
    """
    Extract player rows from notes and/or images using OpenAI.
    If both are provided, sends one request with text + images for best context.
    Returns list of dicts with keys: raw_name, buyin, cashout, final_stack, net_change.
    """
    if not OPENAI_API_KEY:
        return []
    notes = (notes or "").strip()
    image_paths = image_paths or []
    if not notes and not image_paths:
        return []
    valid_paths = [p for p in image_paths if p and getattr(p, "is_file", lambda: False)() and p.is_file()]
    if not notes and not valid_paths:
        return []

    content: list[dict] = []
    if notes:
        content.append({
            "type": "text",
            "text": "Pasted notes:\n\n" + notes + "\n\n" + _EXTRACT_PROMPT,
        })
    for path in valid_paths:
        media_type, b64 = _encode_image(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64}"},
        })
    if not content:
        return []
    # If we only had images, prepend the prompt
    if content and content[0].get("type") != "text":
        content.insert(0, {"type": "text", "text": _EXTRACT_PROMPT})

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=1024,
        )
        text = (response.choices[0].message.content or "").strip()
        return _parse_response(text)
    except Exception:
        return []


def extract_game_from_image(image_path: Path) -> list[dict[str, str]]:
    """Single-image convenience; use extract_game(..., image_paths=[path]) for multi-image."""
    return extract_game(image_paths=[image_path])
