"""Fetch the Edge of Eternities subset of Special Guests from Scryfall.

Writes `data/special_guests_eoe.json` — the 10 Special Guests cards
(set code ``spg``) released on 2025-08-01 alongside Edge of
Eternities. Special Guests is a cross-set premium-reprint series, so
we filter by release date to get only the EoE-shipped subset.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

QUERY = "set:spg date:2025-08-01"
OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "special_guests_eoe.json"
)
USER_AGENT = "mtg-bot/0.0.1 (learning project)"
REQUEST_DELAY_SEC = 0.1


def fetch(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all() -> list[dict]:
    url = (
        "https://api.scryfall.com/cards/search?"
        f"q={urllib.parse.quote(QUERY)}&unique=prints&order=set"
    )
    cards: list[dict] = []
    while url:
        page = fetch(url)
        cards.extend(page.get("data", []))
        url = page.get("next_page") if page.get("has_more") else None
        if url:
            time.sleep(REQUEST_DELAY_SEC)
    return cards


def main() -> int:
    print(f"Fetching Scryfall query {QUERY!r}...")
    cards = fetch_all()
    if not cards:
        print("No cards returned.", file=sys.stderr)
        return 1
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(cards, indent=2), encoding="utf-8")
    print(f"Wrote {len(cards)} cards to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
