"""Fetch all unique cards from the Edge of Eternities set via Scryfall.

Writes `data/edge_of_eternities.json` — a JSON array of Scryfall card objects,
deduped by card name (keeps the first printing encountered).

Scryfall asks for a User-Agent and a small delay between requests; we obey.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SET_CODE = "eoe"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "edge_of_eternities.json"
USER_AGENT = "mtg-bot/0.0.1 (learning project)"
REQUEST_DELAY_SEC = 0.1


def fetch(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_cards(set_code: str) -> list[dict]:
    query = f"set:{set_code}"
    url = f"https://api.scryfall.com/cards/search?q={urllib.parse.quote(query)}&unique=cards&order=set"
    cards: list[dict] = []
    while url:
        page = fetch(url)
        cards.extend(page.get("data", []))
        url = page.get("next_page") if page.get("has_more") else None
        if url:
            time.sleep(REQUEST_DELAY_SEC)
    return cards


def main() -> int:
    print(f"Fetching set {SET_CODE!r} from Scryfall...")
    cards = fetch_all_cards(SET_CODE)
    if not cards:
        print(f"No cards returned for set {SET_CODE!r}. Is the set code right?", file=sys.stderr)
        return 1

    seen: set[str] = set()
    deduped: list[dict] = []
    for c in cards:
        name = c.get("name", "")
        if name in seen:
            continue
        seen.add(name)
        deduped.append(c)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    print(f"Wrote {len(deduped)} unique cards to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
