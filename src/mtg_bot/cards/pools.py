"""Card-pool registry: which Scryfall JSON dumps feed the parser.

The project's **target** pool is the PowerLSV cube
(``data/cube_power_lsv.json``, regenerate via ``scripts/fetch_cube.py``).
The Edge of Eternities pools (``eoe`` + Stellar Sights + EoE Special
Guests + Duskmourn) remain loadable because the engine's test fixtures
are written against those cards.

Pool names (``MTG_BOT_CARD_POOL`` env var):

- ``all`` (default): EoE pools + cube, deduped by name (first wins).
  Production and tests see the same source; nothing is dropped.
- ``cube``: the PowerLSV cube + basic lands only. Use this for
  coverage measurement, cube deck-pool generation, and cube self-play.
- ``eoe``: the legacy four EoE-era files only.

Unknown values raise so a typo never silently becomes a different pool.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

POOL_ENV_VAR = "MTG_BOT_CARD_POOL"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"

CUBE_POOL_FILES: tuple[str, ...] = ("cube_power_lsv.json",)
EOE_POOL_FILES: tuple[str, ...] = (
    "edge_of_eternities.json",
    "stellar_sights.json",
    "special_guests_eoe.json",
    "duskmourn.json",
)
POOLS: dict[str, tuple[str, ...]] = {
    "all": EOE_POOL_FILES + CUBE_POOL_FILES,
    "cube": CUBE_POOL_FILES,
    "eoe": EOE_POOL_FILES,
}
DEFAULT_POOL = "all"
# The pool the modeling campaign, deck pool, and self-play target.
TARGET_POOL = "cube"


def resolve_pool_name(value: str | None) -> str:
    """Normalize an env-var / CLI value to a registered pool name."""
    normalized = (value or DEFAULT_POOL).strip().lower()
    if normalized not in POOLS:
        raise ValueError(
            f"unknown {POOL_ENV_VAR} value: {value!r} "
            f"(expected one of {sorted(POOLS)})"
        )
    return normalized


def active_pool_name() -> str:
    return resolve_pool_name(os.environ.get(POOL_ENV_VAR))


def pool_data_paths(pool: str | None = None, *, data_dir: Path = DATA_DIR) -> tuple[Path, ...]:
    """Absolute paths of the JSON dumps that make up ``pool``
    (``None`` -> the env-selected pool)."""
    name = resolve_pool_name(pool) if pool is not None else active_pool_name()
    return tuple(data_dir / f for f in POOLS[name])


def load_pool_cards(pool: str | None = None, *, data_dir: Path = DATA_DIR) -> list[dict]:
    """Every Scryfall card object in ``pool``, deduped by name (first
    file wins). A missing dump raises ``FileNotFoundError`` naming the
    script that regenerates it -- a half-loaded pool must not ship."""
    cards: list[dict] = []
    seen: set[str] = set()
    for path in pool_data_paths(pool, data_dir=data_dir):
        if not path.exists():
            hint = (
                "scripts/fetch_cube.py" if path.name in CUBE_POOL_FILES
                else "scripts/fetch_*.py"
            )
            raise FileNotFoundError(
                f"card pool file missing: {path} (regenerate via {hint})"
            )
        with path.open("r", encoding="utf-8") as f:
            for card in json.load(f):
                name = card["name"]
                if name in seen:
                    continue
                seen.add(name)
                cards.append(card)
    return cards


def pool_card_names(pool: str, *, data_dir: Path = DATA_DIR) -> frozenset[str]:
    """Names present in ``pool``'s raw dumps (claimed or not)."""
    return frozenset(c["name"] for c in load_pool_cards(pool, data_dir=data_dir))
