"""Invariant tests for :class:`mtg_bot.cards.base.CardPrinting`.

The printing dataclass is ``@dataclass(frozen=True)``; transitively all
of its fields must be hashable for the dataclass-derived ``__hash__``
to work. Search-side caches (e.g. the belief-weighted determinizer's
``(printings_tuple, history_index)`` policy cache) build dict keys
from tuples of printings, so ``hash(printing)`` is exercised in the
hot loop of ISMCTS evaluation and any unhashable nested field
(historic example: ``EventPattern.subject_filters: dict``) propagates
all the way up and silently breaks caching.

These tests pin the invariant against both the synthetic G/R deck used
by Stage-1 self-play and the full real-EoE pool surfaced by
``OracleParserCardSource``.
"""

from __future__ import annotations

from mtg_bot.agents import RandomAgent
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.simulate import setup_game


def test_card_printings_in_synthetic_decks_are_hashable():
    """Every printing reachable from a default G/R synthetic-deck game
    setup must be hashable. Covers hand, library, battlefield (at
    setup just lands aren't on the battlefield yet, but exercise the
    other zones for symmetry), graveyard, and exile.
    """
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=0,
    )
    seen = 0
    for player in state.players:
        for zone in (player.hand, player.library, player.graveyard,
                     player.exile):
            for card in zone:
                # Must not raise — the dataclass-derived __hash__ runs
                # over every field's hash, so any unhashable nested
                # field (dict, list, set) surfaces here.
                hash(card.printing)
                seen += 1
    # Sanity: at least the hand+library cards are present.
    assert seen > 0


def test_real_eoe_card_printings_are_hashable():
    """Every printing surfaced by the real EoE oracle parser must
    be hashable. This is the broadest possible CardPrinting fixture
    — any field that can be populated by the parser is exercised
    for at least one printing.
    """
    src = OracleParserCardSource()
    printings = list(src.get_printings().values())
    assert printings, "parser source returned no printings"
    for p in printings:
        hash(p)


def test_card_printings_usable_as_dict_keys():
    """End-to-end: a tuple of printings (the shape used by
    ``_opponent_hand_key`` in :mod:`mtg_bot.search.belief`) must be
    usable as a dict key. Equality + hashability together — equal
    printings collide on the same key, distinct printings don't.
    """
    src = OracleParserCardSource()
    printings = list(src.get_printings().values())
    assert len(printings) >= 2

    cache: dict[tuple, int] = {}
    key_a = (printings[0], printings[1])
    key_b = (printings[0], printings[1])  # structurally equal to key_a
    cache[key_a] = 1
    cache[key_b] = 2
    # Same key — second write overwrites first.
    assert len(cache) == 1
    assert cache[key_a] == 2
