"""Vintage Roto P3: rituals, dynamic mana and the Force of Despair sweep
(``cards/parser/roto_mana.py`` / ``effects/generic/roto_mana.py``)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _activate_ability,
    apply_action,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_artifact, make_basic_land, make_creature
from mtg_bot.cards.parser.roto_mana import (
    parse_activate_only_if_condition,
    parse_roto_mana_effect,
)
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import ManaCoin, Zone
from mtg_bot.legal import legal_actions

from tests._roto_helpers import arena, printing, put, to_graveyard, to_hand

MOUNTAIN = make_basic_land("Mountain", "R")
SWAMP = make_basic_land("Swamp", "B")
BEAR = make_creature("Bear", "{1}{G}", 2, 2)


def _pool(state, pid=0):
    return sorted(c.color for c in state.players[pid].mana_pool)


# ---------------------------------------------------------------------------
# Rite of Flame
# ---------------------------------------------------------------------------


def test_rite_of_flame_counts_every_graveyards_copies():
    s = arena()
    rite = printing("Rite of Flame")
    to_graveyard(s, rite, 0)
    to_graveyard(s, rite, 1)
    to_graveyard(s, BEAR, 1)  # other cards don't count
    put(s, MOUNTAIN, 0)
    card = to_hand(s, rite, 0)
    apply_action(s, 0, CastSpell(card.id))
    resolve_top_of_stack(s)
    # {R}{R} plus one {R} per Rite of Flame in each graveyard (the
    # resolving copy is on the stack, not in a graveyard).
    assert _pool(s) == ["R"] * 4
    assert card in s.players[0].graveyard


def test_rite_of_flame_alone_adds_two():
    s = arena()
    put(s, MOUNTAIN, 0)
    card = to_hand(s, printing("Rite of Flame"), 0)
    apply_action(s, 0, CastSpell(card.id))
    resolve_top_of_stack(s)
    assert _pool(s) == ["R", "R"]


def test_cards_named_formula_reads_all_graveyards():
    s = arena()
    to_graveyard(s, BEAR, 0)
    to_graveyard(s, BEAR, 1)
    assert rm.CardsNamedInAllGraveyards("Bear").value(s, 0) == 2
    assert rm.CardsNamedInAllGraveyards("Elk").value(s, 0) == 0


# ---------------------------------------------------------------------------
# Spire of Industry
# ---------------------------------------------------------------------------


def _spire_mana_ability_index(spire):
    return next(
        i for i, a in enumerate(spire.printing.activated_abilities)
        if a.activate_only_if is not None
    )


def test_spire_any_color_needs_an_artifact_and_costs_life():
    s = arena()
    spire = put(s, printing("Spire of Industry"), 0)
    idx = _spire_mana_ability_index(spire)
    offered = ActivateAbility(source_id=spire.id, ability_index=idx)
    assert offered not in legal_actions(s, 0)
    put(s, make_artifact("Trinket", "{1}"), 0)
    assert offered in legal_actions(s, 0)
    _activate_ability(s, 0, spire.id, idx)
    assert spire.tapped
    assert s.players[0].life == 19
    assert _pool(s) == ["any"]


def test_spire_taps_for_colorless_without_an_artifact():
    s = arena()
    spire = put(s, printing("Spire of Industry"), 0)
    assert spire.printing.produces == frozenset({"C"})
    # An opponent's artifact doesn't count.
    put(s, make_artifact("Trinket", "{1}"), 1)
    idx = _spire_mana_ability_index(spire)
    assert ActivateAbility(source_id=spire.id, ability_index=idx) not in (
        legal_actions(s, 0)
    )


def test_activate_only_if_control_type_rider_grammar():
    cond = parse_activate_only_if_condition("you control a creature")
    s = arena()
    assert not cond.matches(s, 0)
    put(s, BEAR, 0)
    assert cond.matches(s, 0)
    assert parse_activate_only_if_condition("you control a goblin") is None


# ---------------------------------------------------------------------------
# Force of Despair
# ---------------------------------------------------------------------------


def _fresh_creature(state, controller):
    """A creature that enters this turn through the ETB pipeline."""
    obj = state.new_object(BEAR, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def test_force_of_despair_destroys_only_creatures_that_entered_this_turn():
    s = arena(active=1)
    s.priority_player_idx = 0
    old = put(s, BEAR, 1)
    new_theirs = _fresh_creature(s, 1)
    new_mine = _fresh_creature(s, 0)
    force = to_hand(s, printing("Force of Despair"), 0)
    to_hand(s, printing("Rite of Flame"), 0)  # not black
    black = to_hand(s, printing("Force of Despair"), 0)
    # Not my turn: the pitch alternative cost is offered.
    assert CastSpell(force.id, cast_for_free=True) in legal_actions(s, 0)
    apply_action(s, 0, CastSpell(force.id, cast_for_free=True))
    assert black in s.players[0].exile
    resolve_top_of_stack(s)
    assert old in s.battlefield
    assert new_theirs not in s.battlefield
    assert new_mine not in s.battlefield


def test_force_of_despair_alt_cost_only_on_opponents_turn():
    s = arena(active=0)
    force = to_hand(s, printing("Force of Despair"), 0)
    to_hand(s, printing("Force of Despair"), 0)
    assert CastSpell(force.id, cast_for_free=True) not in legal_actions(s, 0)


def test_land_creature_played_this_turn_counts_as_entered():
    from mtg_bot.actions import PlayLand

    s = arena(active=0)
    card = to_hand(s, printing("Dryad Arbor"), 0)
    apply_action(s, 0, PlayLand(card.id))
    assert rm.EnteredThisTurn().test(card, s)
    s.turn_number += 1
    assert not rm.EnteredThisTurn().test(card, s)


def test_entered_this_turn_grammar_requires_a_destroy_base():
    assert parse_roto_mana_effect("destroy all creatures that entered this turn")
    assert parse_roto_mana_effect(
        "destroy all frobnicators that entered this turn"
    ) is None
