"""Tests for Chorale of the Void — attacks reanimate defender-graveyard
creature + Void-conditional end-step sacrifice. Also exercises the new
enchanted_creature_attacks trigger on auras."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.actions import drain_stack
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    ChoraleReanimateDefenderGraveCreatureEffect,
    SacrificeSelfUnlessVoidActive,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_beginning_of_end_step_triggers
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


def _put_in_graveyard(state, printing, owner_id=1):
    c = state.new_object(printing, owner_id, Zone.GRAVEYARD)
    state.players[owner_id].graveyard.append(c)
    return c


# -----------------------
# ChoraleReanimateDefenderGraveCreatureEffect
# -----------------------


def test_effect_legal_targets_opp_graveyard_creatures_only():
    state = _new_state()
    own_bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    opp_bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    legal = ChoraleReanimateDefenderGraveCreatureEffect().legal_targets(state, 0)
    ids = {tid for kind, tid in legal if kind == "graveyard_creature"}
    assert opp_bear.id in ids
    assert own_bear.id not in ids


def test_effect_resolve_puts_card_on_battlefield_tapped_attacking():
    state = _new_state()
    enemy_bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    ChoraleReanimateDefenderGraveCreatureEffect().resolve(
        state, 0, (("graveyard_creature", enemy_bear.id),),
    )
    assert enemy_bear in state.battlefield
    assert enemy_bear.controller_id == 0
    assert enemy_bear.tapped
    assert enemy_bear.attacking
    assert enemy_bear not in state.players[1].graveyard


def test_effect_describe():
    d = ChoraleReanimateDefenderGraveCreatureEffect().describe()
    assert "defending player" in d and "graveyard" in d


# -----------------------
# SacrificeSelfUnlessVoidActive
# -----------------------


def test_sac_fires_when_void_inactive():
    state = _new_state()
    aura = _put(state, _PRINTINGS["Chorale of the Void"])
    state.resolving_source = aura
    try:
        SacrificeSelfUnlessVoidActive().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert aura not in state.battlefield


def test_sac_skips_when_void_active():
    state = _new_state()
    aura = _put(state, _PRINTINGS["Chorale of the Void"])
    state.permanent_left_battlefield_this_turn = True  # Void active
    state.resolving_source = aura
    try:
        SacrificeSelfUnlessVoidActive().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert aura in state.battlefield


# -----------------------
# Integration: aura attacks trigger fires
# -----------------------


def test_aura_on_attacker_fires_enchanted_attacks_trigger():
    state = _new_state()
    # P0's bear enchanted with Chorale.
    my_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    my_bear.summoning_sick = False
    aura = _put(state, _PRINTINGS["Chorale of the Void"], owner_id=0, attached_to=my_bear.id)
    # Enemy has a creature in graveyard.
    enemy_bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    # My bear attacks → Chorale's trigger should reanimate enemy bear
    # under my control.
    declare_attackers(state, [my_bear.id])
    drain_stack(state)
    assert enemy_bear in state.battlefield
    assert enemy_bear.controller_id == 0
    assert enemy_bear.tapped
    assert enemy_bear.attacking


def test_chorale_end_step_sacrifice_integration():
    state = _new_state()
    my_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(
        state, _PRINTINGS["Chorale of the Void"], owner_id=0,
        attached_to=my_bear.id,
    )
    # Void inactive → end step sacrifices Chorale.
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert aura not in state.battlefield


def test_chorale_printing_has_both_triggers():
    c = _PRINTINGS["Chorale of the Void"]
    triggers = {_legacy_or_inferred_key(ab, c) for ab in c.triggered_abilities}
    assert "enchanted_creature_attacks" in triggers
    assert "beginning_of_end_step" in triggers
