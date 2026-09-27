"""Synthetic cube deck pool.

There is no 17lands-style corpus for a cube (CubeCobra exposes no deck
API), so self-play on the cube pool runs on generated 40-card singleton
decks: two colors, ``n_spells`` nonland cards drawn from the cube cards
the parser claims whose color identity fits the deck's colors
(colorless artifacts always fit), plus basic lands split by the deck's
colored mana symbols.

Every deck is a ``mtg_bot.decks.Deck`` so the existing ``--deck-pool``
machinery (``decks_to_json`` / ``decks_from_json``) is reused unchanged.

Loud failure: a color combination with fewer claimed candidates than
``n_spells`` raises ``InsufficientCoverageError``. A thin pool must
never silently degrade into near-duplicate decks.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from mtg_bot.decks import Deck

COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")
BASIC_FOR_COLOR: dict[str, str] = {
    "W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain",
    "G": "Forest",
}
COLOR_PAIRS: tuple[str, ...] = (
    "WU", "WB", "WR", "WG", "UB", "UR", "UG", "BR", "BG", "RG",
)
DEFAULT_COMBOS: tuple[str, ...] = COLOR_PAIRS
DEFAULT_N_SPELLS = 23
DEFAULT_N_LANDS = 17

_PIP_RE = re.compile(r"\{([^}]*)\}")


class InsufficientCoverageError(ValueError):
    """Raised when a color combination lacks enough claimed cube cards."""


def color_identity(card: dict) -> frozenset[str]:
    return frozenset(card.get("color_identity", []))


def is_land(card: dict) -> bool:
    front = card.get("type_line", "").split(" // ")[0]
    return "Land" in front


def colored_pips(mana_cost: str) -> Counter:
    """Count colored mana symbols in a cost string (hybrid counts each
    half; generic / colorless / X symbols are ignored)."""
    pips: Counter = Counter()
    for sym in _PIP_RE.findall(mana_cost or ""):
        for part in sym.split("/"):
            if part in COLORS:
                pips[part] += 1
    return pips


def eligible_spells(
    cards: Iterable[dict], colors: str, claimed: Iterable[str],
) -> list[dict]:
    """Claimed, nonland cube cards whose color identity fits ``colors``."""
    claimed_set = set(claimed)
    allowed = frozenset(colors)
    return [
        c for c in cards
        if c["name"] in claimed_set
        and not is_land(c)
        and color_identity(c) <= allowed
    ]


def basic_land_split(
    spells: Sequence[dict], colors: str, n_lands: int,
) -> list[str]:
    """Split ``n_lands`` basics across ``colors`` proportionally to the
    colored pips in the chosen spells (at least one of each color)."""
    pips = colored_pips("".join(c.get("mana_cost", "") for c in spells))
    cols = list(colors)
    counts = {c: 1 for c in cols}
    remaining = n_lands - len(cols)
    total_pips = sum(pips[c] for c in cols)
    if total_pips == 0:
        weights = {c: 1.0 / len(cols) for c in cols}
    else:
        weights = {c: pips[c] / total_pips for c in cols}
    # Largest-remainder apportionment keeps the total exact.
    raw = {c: weights[c] * remaining for c in cols}
    for c in cols:
        counts[c] += int(raw[c])
    leftover = n_lands - sum(counts.values())
    by_fraction = sorted(
        cols, key=lambda c: raw[c] - int(raw[c]), reverse=True,
    )
    for c in by_fraction[:leftover]:
        counts[c] += 1
    lands: list[str] = []
    for c in cols:
        lands.extend([BASIC_FOR_COLOR[c]] * counts[c])
    return lands


@dataclass(frozen=True)
class ComboReport:
    colors: str
    eligible: int
    needed: int

    @property
    def feasible(self) -> bool:
        return self.eligible >= self.needed


def feasibility(
    cards: Sequence[dict], claimed: Iterable[str],
    *, combos: Sequence[str] = DEFAULT_COMBOS,
    n_spells: int = DEFAULT_N_SPELLS,
) -> list[ComboReport]:
    claimed_set = set(claimed)
    return [
        ComboReport(
            colors=combo,
            eligible=len(eligible_spells(cards, combo, claimed_set)),
            needed=n_spells,
        )
        for combo in combos
    ]


def build_deck(
    cards: Sequence[dict], colors: str, claimed: Iterable[str],
    rng: random.Random,
    *, n_spells: int = DEFAULT_N_SPELLS, n_lands: int = DEFAULT_N_LANDS,
    deck_id: str = "cube",
) -> Deck:
    pool = eligible_spells(cards, colors, claimed)
    if len(pool) < n_spells:
        raise InsufficientCoverageError(
            f"{colors}: only {len(pool)} claimed cube cards fit, "
            f"need {n_spells}"
        )
    spells = rng.sample(pool, n_spells)
    names = [c["name"] for c in spells]
    names += basic_land_split(spells, colors, n_lands)
    return Deck(
        draft_id=deck_id, build_index=0, cards=sorted(names),
        main_colors=colors,
    )


def build_deck_pool(
    cards: Sequence[dict], claimed: Iterable[str],
    *, n_decks: int, seed: int = 0, combos: Sequence[str] = DEFAULT_COMBOS,
    n_spells: int = DEFAULT_N_SPELLS, n_lands: int = DEFAULT_N_LANDS,
) -> list[Deck]:
    """``n_decks`` decks cycling through ``combos``. Raises
    ``InsufficientCoverageError`` up front if any combo is infeasible."""
    claimed_set = set(claimed)
    reports = feasibility(
        cards, claimed_set, combos=combos, n_spells=n_spells,
    )
    infeasible = [r for r in reports if not r.feasible]
    if infeasible:
        detail = ", ".join(
            f"{r.colors}={r.eligible}/{r.needed}" for r in infeasible
        )
        raise InsufficientCoverageError(
            f"{len(infeasible)} of {len(combos)} color combos lack "
            f"claimed cube cards: {detail}"
        )
    rng = random.Random(seed)
    decks: list[Deck] = []
    for i in range(n_decks):
        combo = combos[i % len(combos)]
        decks.append(build_deck(
            cards, combo, claimed_set, rng,
            n_spells=n_spells, n_lands=n_lands,
            deck_id=f"cube-{combo}-{i:05d}",
        ))
    return decks
