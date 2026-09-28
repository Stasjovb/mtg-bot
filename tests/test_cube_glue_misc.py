"""Cube glue bucket: Gleemox (deck-construction statement) and other
single-card odds and ends."""

from __future__ import annotations

from mtg_bot.actions import _activate_ability
from mtg_bot.cards.parser.printing_keywords import (
    _parse_deck_construction_statement_line,
)

from tests._cube_glue_helpers import arena, pool_colors, printing, put


def test_deck_construction_statement_recognizer():
    assert _parse_deck_construction_statement_line(
        "This card is banned.", "Gleemox",
    )
    assert _parse_deck_construction_statement_line(
        "A deck can have any number of cards named Rat.", "Rat",
    )
    assert _parse_deck_construction_statement_line(
        "A deck can have up to seven cards named Dwarves.", "Dwarves",
    )
    # A "cards named" statement about another card is not this class.
    assert not _parse_deck_construction_statement_line(
        "A deck can have any number of cards named Rat.", "Gleemox",
    )
    assert not _parse_deck_construction_statement_line(
        "This card is great.", "Gleemox",
    )


def test_gleemox_claims_as_a_mox_with_one_mana_ability():
    p = printing("Gleemox")
    assert p.is_artifact
    assert len(p.activated_abilities) == 1
    assert p.activated_abilities[0].is_mana_ability


def test_gleemox_taps_for_any_color():
    s = arena()
    mox = put(s, printing("Gleemox"), 0)
    _activate_ability(s, 0, mox.id, 0)
    assert mox.tapped
    assert pool_colors(s, 0) == ["any"]  # an any-color coin


# ---------------------------------------------------------------------------
# Mawloc: flavor-word ETB fight + "if that creature would die this turn,
# exile it instead"
# ---------------------------------------------------------------------------


def _mawloc_arena():
    from mtg_bot.cards.base import make_creature

    s = arena()
    bear = put(s, make_creature("Bear", "{1}{G}", 3, 3), 1)
    mine = put(s, make_creature("Elf", "{G}", 1, 1), 0)
    return s, bear, mine


def test_mawloc_parse_shape():
    from mtg_bot.effects.generic.cube_creatures_rmc import SourceFightsTarget

    p = printing("Mawloc")
    fights = [
        t.effect for t in p.triggered_abilities
        if isinstance(t.effect, SourceFightsTarget)
    ]
    assert len(fights) == 1
    eff = fights[0]
    assert eff.optional and eff.exile_if_dies_this_turn
    assert eff.target_count_range() == (0, 1)


def test_mawloc_fight_targets_only_opponents_creatures_and_exiles():
    from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions

    s, bear, mine = _mawloc_arena()
    maw = s.new_object(printing("Mawloc"), 0, Zone.HAND)
    put_into_battlefield(s, maw, controller_id=0)
    maw.plus_one_counters = 3  # as if cast with X=3: a 5/5
    item = s.stack[-1]
    eff = item.ability.effect
    legal = eff.legal_targets(s, 0)
    assert ("creature", bear.id) in legal
    assert all(t[1] != mine.id for t in legal)
    assert item.targets == (("creature", bear.id),)
    resolve_top_of_stack(s)
    state_based_actions(s)
    assert bear not in s.battlefield
    assert bear in s.players[1].exile
    assert bear not in s.players[1].graveyard
    assert maw.damage == 3


def test_plain_fight_still_parses_without_rider():
    from mtg_bot.cards.parser.creature_rmc_grammar import parse_rmc_effect

    eff = parse_rmc_effect("this creature fights target creature")
    assert eff is not None and not eff.exile_if_dies_this_turn
    assert parse_rmc_effect(
        "this creature fights target creature with frobnitz"
    ) is None
