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


# ---------------------------------------------------------------------------
# Shelldock Isle: Hideaway 4 + conditional free play
# ---------------------------------------------------------------------------


def _shelldock_setup(library_extra=0, top=None):
    from mtg_bot.actions import PlayLand, apply_action, resolve_top_of_stack
    from mtg_bot.cards import BASIC_LANDS

    from tests._cube_glue_helpers import agent, to_hand, to_library

    s = arena()
    top = top or [BASIC_LANDS["Island"]] * 4
    first = [to_library(s, pr, 0) for pr in top]
    for _ in range(library_extra):
        to_library(s, BASIC_LANDS["Island"], 0)
    isle = to_hand(s, printing("Shelldock Isle"), 0)
    agent(s, 0).library_pick = first[1].id
    apply_action(s, 0, PlayLand(isle.id))
    resolve_top_of_stack(s)
    return s, isle, first


def test_hideaway_exiles_one_face_down_and_bottoms_the_rest():
    s, isle, first = _shelldock_setup(library_extra=2)
    hidden = first[1]
    assert hidden in s.players[0].exile
    assert hidden.imprinted_on == (isle.id, isle.etb_timestamp)
    assert hidden.publicly_known_to == frozenset({0}) or (
        1 not in hidden.publicly_known_to
    )
    lib = s.players[0].library
    assert len(lib) == 5
    assert set(c.id for c in lib[-3:]) == {first[0].id, first[2].id, first[3].id}
    assert isle.tapped  # "This land enters tapped."


def _activate_isle(s, isle):
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.game import ManaCoin

    isle.tapped = False
    s.players[0].mana_pool.append(ManaCoin(color="U"))
    idx = next(
        i for i, a in enumerate(isle.printing.activated_abilities)
        if not a.is_mana_ability
    )
    _activate_ability(s, 0, isle.id, idx)
    resolve_top_of_stack(s)


def test_shelldock_does_nothing_while_every_library_is_big():
    from mtg_bot.cards.base import make_sorcery
    from mtg_bot.effects.generic import DrawCards

    from tests._cube_glue_helpers import to_library

    spell = make_sorcery("Ancestral", "{U}", DrawCards(amount=1))
    s, isle, first = _shelldock_setup(
        library_extra=0, top=[spell, spell, spell, spell],
    )
    for _ in range(25):
        to_library(s, spell, 0)
        to_library(s, spell, 1)
    _activate_isle(s, isle)
    assert first[1] in s.players[0].exile
    assert s.stack == []


def test_shelldock_casts_the_hidden_spell_free_with_a_small_library():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import make_sorcery
    from mtg_bot.effects.generic import DrawCards

    spell = make_sorcery("Ancestral", "{5}{U}", DrawCards(amount=1))
    s, isle, first = _shelldock_setup(top=[spell, spell, spell, spell])
    _activate_isle(s, isle)
    assert s.stack and s.stack[-1].source is first[1]
    resolve_top_of_stack(s)
    assert first[1] in s.players[0].graveyard


def test_shelldock_plays_a_hidden_land_only_with_a_land_drop():
    s, isle, first = _shelldock_setup()
    # The Isle itself used this turn's land drop.
    _activate_isle(s, isle)
    assert first[1] in s.players[0].exile
    s.players[0].lands_played_this_turn = 0
    _activate_isle(s, isle)
    assert first[1] in s.battlefield
    assert s.players[0].lands_played_this_turn == 1


def test_hideaway_recognizer_and_empty_library():
    from mtg_bot.cards.parser.cube_glue_grammar import (
        parse_glue_effect,
        parse_glue_keyword_trigger,
    )
    from mtg_bot.effects.generic.cube_glue import HideawayLookExileOneFaceDown

    assert parse_glue_keyword_trigger("Hideaway 5").effect.n == 5
    assert parse_glue_keyword_trigger("Hideaway") is None
    assert parse_glue_effect(
        "you may play the exiled card without paying its mana cost if a "
        "library has umpteen or fewer cards in it"
    ) is None
    s = arena()
    HideawayLookExileOneFaceDown(n=4).resolve(s, 0)
    assert s.players[0].exile == []
    assert "exile one face down" in HideawayLookExileOneFaceDown().describe()
