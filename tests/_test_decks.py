"""Deck fixtures for tests that just need *some* deck to feed
``setup_game(decks=...)``.

Replaces the synthetic mono-color path that used to live on the
card source (``build_mono_color_deck``). The deck builder there was
a Stage-1 simplification — the production training inputs are real
17lands EoE archetypes — and was removed alongside this module.

Most tests don't care about deck composition: they call
``setup_game(decks=...)``, then either drive specific actions or
play a few turns to exercise engine paths. For those tests, any
60-card deck of cards that exist in the active card source's pool
works. ``simple_test_decklist`` returns one such deck per call and
``simple_test_decklists`` returns the canonical two-seat pair.

For tests that DO care about specific cards (e.g. "P0 must have
exactly 2 Forests in their library at start"), build the decklist
inline — those tests already do that and shouldn't reach for a
generic helper.

The deck builder mirrors the legacy mono-color shape (24 basics +
36 nonland cards in the chosen color or colorless) so the same
breadth of engine code paths gets exercised — casting from hand,
playing lands, etc. The only requirement on the active card
source is that it expose enough cards to fill the 36-card nonland
slots.
"""

from __future__ import annotations

from mtg_bot.cards.pools import pool_card_names
from mtg_bot.cards.source import get_active_source
from mtg_bot.decks import Deck

# The canonical fixture is pinned to the Edge of Eternities-era pool.
# The default active source is the union of that pool and the PowerLSV
# cube (2026-09-27 retarget); drawing the alphabetically-first
# candidates from the union would silently change every fixture game
# (e.g. "Abrade" / "Ancient Tomb" displacing EoE cards) and perturb
# seed-sensitive search tests. Synthetic test sources that share no
# names with the EoE pool fall through to their own cards.
_EOE_NAMES: frozenset[str] = pool_card_names("eoe")


# Same color → basic-land mapping the legacy mono-color path used.
_COLOR_TO_BASIC: dict[str, str] = {
    "W": "Plains", "U": "Island", "B": "Swamp",
    "R": "Mountain", "G": "Forest",
}


def simple_test_decklist(color: str = "G") -> list[str]:
    """Return a 60-card decklist drawn from the active card source.

    24 basics of the chosen color + 36 nonland cards in that color
    (or colorless, since colorless generic costs can be paid from any
    basic land). Deterministic — same color always produces the same
    decklist — so RNG-sensitive tests don't get perturbed by the
    deck-builder picking different cards on different runs.

    Use ``simple_test_decklists`` for the standard two-seat pair.
    """
    if color not in _COLOR_TO_BASIC:
        raise ValueError(
            f"unknown color {color!r}; expected one of "
            f"{sorted(_COLOR_TO_BASIC)}"
        )
    land_name = _COLOR_TO_BASIC[color]
    printings = get_active_source().get_printings()
    candidates = sorted(
        name for name, p in printings.items()
        if "Land" not in p.card_types
        and (color in p.mana_cost.colors or not p.mana_cost.colors)
    )
    eoe_only = [n for n in candidates if n in _EOE_NAMES]
    if eoe_only:
        candidates = eoe_only
    if not candidates:
        raise ValueError(f"no nonland cards in color {color}")
    deck = [candidates[i % len(candidates)] for i in range(36)]
    deck.extend([land_name] * 24)
    return deck


def simple_test_decklists(
    c0: str = "G", c1: str = "R",
) -> list[list[str]]:
    """The canonical two-seat fixture: one decklist per seat,
    structured so callers can pass the result straight to
    ``setup_game(decks=simple_test_decklists())``.

    The default ``("G", "R")`` mirrors the legacy mono-color
    synthetic decks the test suite migrated off of, so keeping the
    default here makes the test diffs purely a constructor swap.
    """
    return [simple_test_decklist(c0), simple_test_decklist(c1)]


def simple_test_deck_pool(
    colors: tuple[str, ...] = ("G", "R"),
) -> list[Deck]:
    """A small ``deck_pool`` for ``run_match`` / ``generate_training_data``
    fixture use. Each color produces one ``Deck`` whose ``cards`` is
    ``simple_test_decklist(color)``. Default is two distinct decks so
    ``_sample_decks_for_game`` returns a real two-deck pair (rather
    than a mirror match) — matches the legacy production behavior of
    sampling distinct archetypes per game.
    """
    return [
        Deck(
            draft_id=f"{color.lower()}_deck",
            build_index=0,
            cards=simple_test_decklist(color),
        )
        for color in colors
    ]
