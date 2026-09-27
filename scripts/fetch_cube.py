"""Fetch a CubeCobra cube's card list as Scryfall card objects.

Default cube is LSV's powered Vintage cube (``PowerLSV``) -- the
project's target card pool. Writes ``data/cube_power_lsv.json``: a JSON
array of Scryfall card objects, deduped by card name, plus the five
basic lands (a cube list never contains basics, but every deck needs
them). A sidecar ``data/cube_power_lsv.meta.json`` records the cube's
``dateLastUpdated`` / card count so staleness is visible.

Data flow:

1. ``GET https://cubecobra.com/cube/api/cubeJSON/<cube-id>`` -- the
   cube's mainboard with each card's ``details.scryfall_id`` (the
   exact printing the cube owner chose).
2. ``POST https://api.scryfall.com/cards/collection`` in batches of
   75 identifiers -- Scryfall returns full card objects (oracle
   text is always the current Oracle wording regardless of printing).

Run with::

    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/fetch_cube.py
    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/fetch_cube.py --cube LSVCube --out data/cube_lsv.json

Scryfall asks for a User-Agent and a small delay between requests; we obey.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Iterator

DEFAULT_CUBE_ID = "PowerLSV"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_PATH = REPO_ROOT / "data" / "cube_power_lsv.json"
USER_AGENT = "mtg-bot/0.0.1 (learning project)"
REQUEST_DELAY_SEC = 0.1
SCRYFALL_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
SCRYFALL_COLLECTION_BATCH = 75  # documented hard limit per request
CUBECOBRA_JSON_URL = "https://cubecobra.com/cube/api/cubeJSON/{cube_id}"

BASIC_LAND_NAMES: tuple[str, ...] = (
    "Plains", "Island", "Swamp", "Mountain", "Forest",
)

# Injectable HTTP seams so tests never touch the network.
GetJson = Callable[[str], dict]
PostJson = Callable[[str, dict], dict]


def _request(url: str, data: bytes | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str) -> dict:
    return _request(url)


def post_json(url: str, payload: dict) -> dict:
    return _request(url, json.dumps(payload).encode("utf-8"))


def extract_scryfall_ids(cube_json: dict) -> list[str]:
    """Mainboard ``details.scryfall_id`` values, in cube order, deduped.

    Raises ``ValueError`` when the payload has no mainboard or a card
    lacks a Scryfall id -- a half-fetched pool must never ship silently.
    """
    boards = cube_json.get("cards")
    if not isinstance(boards, dict) or "mainboard" not in boards:
        raise ValueError("cube JSON has no cards.mainboard")
    ids: list[str] = []
    seen: set[str] = set()
    for entry in boards["mainboard"]:
        details = entry.get("details") or {}
        sid = details.get("scryfall_id") or entry.get("cardID")
        if not sid:
            raise ValueError(
                f"cube card {entry.get('name') or details.get('name')!r} "
                "has no scryfall_id"
            )
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)
    if not ids:
        raise ValueError("cube mainboard is empty")
    return ids


def chunked(items: Iterable, size: int) -> Iterator[list]:
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def fetch_collection(
    identifiers: list[dict],
    *,
    post: PostJson | None = None,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> list[dict]:
    """Resolve Scryfall identifiers (``{"id": ...}`` / ``{"name": ...}``)
    to card objects. Raises if Scryfall reports any identifier as
    not found -- silent drops would shrink the pool unnoticed."""
    # Resolved at call time (not as a def-time default) so tests can
    # monkeypatch the module-level ``post_json``.
    post = post or post_json
    cards: list[dict] = []
    not_found: list[dict] = []
    for batch in chunked(identifiers, SCRYFALL_COLLECTION_BATCH):
        page = post(SCRYFALL_COLLECTION_URL, {"identifiers": batch})
        cards.extend(page.get("data", []))
        not_found.extend(page.get("not_found", []))
        if delay_sec:
            time.sleep(delay_sec)
    if not_found:
        raise ValueError(f"Scryfall could not resolve {len(not_found)} "
                         f"identifiers: {not_found[:5]}")
    return cards


def dedupe_by_name(cards: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in cards:
        name = c.get("name", "")
        if name in seen:
            continue
        seen.add(name)
        out.append(c)
    return out


def build_pool(
    cube_json: dict,
    *,
    post: PostJson | None = None,
    delay_sec: float = REQUEST_DELAY_SEC,
    basics: tuple[str, ...] = BASIC_LAND_NAMES,
) -> list[dict]:
    """Cube mainboard as Scryfall objects + the basic lands, deduped."""
    ids = extract_scryfall_ids(cube_json)
    identifiers = [{"id": sid} for sid in ids]
    identifiers += [{"name": n} for n in basics]
    cards = fetch_collection(identifiers, post=post, delay_sec=delay_sec)
    return dedupe_by_name(cards)


def cube_metadata(cube_json: dict, n_cards: int) -> dict:
    updated_ms = cube_json.get("dateLastUpdated")
    updated_iso = (
        _dt.datetime.fromtimestamp(updated_ms / 1000, _dt.timezone.utc)
        .isoformat()
        if isinstance(updated_ms, (int, float)) else None
    )
    return {
        "cube_id": cube_json.get("shortId"),
        "cube_name": cube_json.get("name"),
        "cube_card_count": cube_json.get("cardCount"),
        "cube_last_updated": updated_iso,
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "pool_card_count": n_cards,
        "includes_basic_lands": list(BASIC_LAND_NAMES),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cube", default=DEFAULT_CUBE_ID,
                        help="CubeCobra cube id (default PowerLSV)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH,
                        help="output JSON path")
    args = parser.parse_args(argv)

    print(f"Fetching cube {args.cube!r} from CubeCobra...")
    cube_json = get_json(CUBECOBRA_JSON_URL.format(cube_id=args.cube))
    pool = build_pool(cube_json)
    if not pool:
        print("No cards resolved.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pool, indent=2), encoding="utf-8")
    meta_path = args.out.with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps(cube_metadata(cube_json, len(pool)), indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(pool)} cards to {args.out} (meta: {meta_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
