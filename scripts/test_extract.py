#!/usr/bin/env python3
"""Run LLM extraction on image path(s). Uses OPENAI_API_KEY from env.
Usage: OPENAI_API_KEY=sk-... python scripts/test_extract.py [image1.png image2.png ...]
"""
import json
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PLAYER_ALIASES
from extract_game import extract_game


def main():
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        # Default: Cursor assets from user's screenshots
        base = Path(__file__).resolve().parent.parent
        cursor_assets = base.parent / ".cursor" / "projects" / base.name.replace(" ", "-") / "assets"
        if not cursor_assets.is_dir():
            # Try workspace assets
            cursor_assets = base / "assets"
        paths = sorted(cursor_assets.glob("Screenshot*.png")) if cursor_assets.is_dir() else []
        if not paths:
            print("No image paths. Usage: OPENAI_API_KEY=sk-... python scripts/test_extract.py image1.png [image2.png ...]")
            sys.exit(1)

    player_names = ["Cam Pal", "BK", "Rohan", "Arjun Garg", "Tyler Tsay", "Arjun Mohan", "Nick Pham", "FrankFish"]
    alias_map = PLAYER_ALIASES or {}

    print("Extracting from", len(paths), "image(s). Key from env:", "set" if __import__("os").getenv("OPENAI_API_KEY") else "NOT SET")
    print("-" * 60)

    for i, path in enumerate(paths):
        if not path.is_file():
            print(f"[{i+1}] SKIP (not a file): {path}")
            continue
        print(f"\n[{i+1}] {path.name}")
        result = extract_game(
            image_paths=[path],
            image_display_names=[path.name],
            player_names=player_names,
            alias_map=alias_map,
        )
        rows = result.get("rows") or []
        date = result.get("suggested_played_at") or "(none)"
        print(f"    suggested_played_at: {date}")
        print(f"    players: {len(rows)}")
        for r in rows:
            print(f"      - {r.get('raw_name')!r} | buyin={r.get('buyin')} cashout={r.get('cashout')} stack={r.get('final_stack')} net={r.get('net_change')} | suggested={r.get('suggested_player_name', '')!r}")
        print(json.dumps({"suggested_played_at": date, "players": rows}, indent=2))

    print("\nDone.")


if __name__ == "__main__":
    main()
