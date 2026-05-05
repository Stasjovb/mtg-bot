"""Tiny deck fixtures for tests that just need *some* deck to feed
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

The decks are deliberately tiny in card-name variety (one creature
per color + the matching basic) so the underlying card-data load
stays fast and the deterministic RNG-driven tests don't have their
expected outputs perturbed by the deck-builder picking different
cards.
"""

from __future__ import annotations

from mtg_bot.cards.source import get_active_source


# Pinned (creature_name, basic_land) pairs for each color. These
# names come from the EoE card pool and have stayed put across
# parser-claim revisions; they're checked at import time below so
# a future card-data swap that drops one of these surfaces loudly
# rather than silently making every test fixture deck empty.
_COLOR_TO_CARDS: dict[str, tuple[str, str]] = {
    "W": ("Astelli Reclaimer", "Plains"),
    "U": ("Cloudsculpt Technician", "Island"),
    "B": ("Beamsaw Prospector", "Swamp"),
    "R": ("Frontline War-Rager", "Mountain"),
    "G": ("Blooming Stinger", "Forest"),
}


def simple_test_decklist(color: str = "G") -> list[str]:
    """Return a 60-card decklist of cards in the active source.

    24 of the matching basic land + 36 copies of one creature in
    that color. Deterministic and tiny; sized to the legacy 60-card
    pre-EOE-pool fixture decks so existing tests' library-size /
    hand-size assertions continue to work without modification.

    Use ``simple_test_decklists`` for the standard two-seat pair.
    """
    if color not in _COLOR_TO_CARDS:
        raise ValueError(
            f"unknown color {color!r}; expected one of "
            f"{sorted(_COLOR_TO_CARDS)}"
        )
    creature, land = _COLOR_TO_CARDS[color]
    printings = get_active_source().get_printings()
    if creature not in printings or land not in printings:
        raise RuntimeError(
            f"test fixture cards {creature!r} / {land!r} are not in "
            f"the active card source's pool. The source has likely "
            f"changed; pick a replacement card name from "
            f"``get_active_source().get_printings()`` and update "
            f"``_COLOR_TO_CARDS`` in this module."
        )
    return [creature] * 36 + [land] * 24


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
