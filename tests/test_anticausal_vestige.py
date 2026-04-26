"""Tests for Anticausal Vestige's leaves-battlefield draw + may-put
permanent from hand ETB."""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import AnticausalVestigeLeavesEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _stock_library(state, player_id, n):
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# Effect-level
# -----------------------


def test_effect_describe():
    d = AnticausalVestigeLeavesEffect().describe()
    assert "draw a card" in d and "lands you control" in d


def test_effect_draws_and_puts_permanent_onto_battlefield():
    state = _new_state()
    _stock_library(state, 0, 3)
    # 4 lands → X = 4. Memorial Vault MV 4 → legal.
    for _ in range(4):
        land = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(land)
    vault = state.new_object(EOE_SPELLS["Memorial Vault"], 0, Zone.HAND)
    state.players[0].hand.append(vault)
    state.resolving_source = state.new_object(
        EOE_CREATURES["Anticausal Vestige"], 0, Zone.GRAVEYARD,
    )
    try:
        AnticausalVestigeLeavesEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # Drew 1 card.
    assert any(c.printing.name == "Plains" for c in state.players[0].hand)
    # Memorial Vault is on battlefield tapped.
    assert vault in state.battlefield
    assert vault.tapped


def test_effect_drops_permanent_card_when_mana_value_too_high():
    state = _new_state()
    _stock_library(state, 0, 3)
    # Only 1 land → X = 1. Memorial Vault MV 4 not legal.
    land = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    vault = state.new_object(EOE_SPELLS["Memorial Vault"], 0, Zone.HAND)
    state.players[0].hand.append(vault)
    AnticausalVestigeLeavesEffect().resolve(state, 0, ())
    # Drew a card, but vault still in hand.
    assert vault in state.players[0].hand


def test_effect_draws_even_when_hand_is_empty():
    """Library has 2 plains, hand empty. Draw fires; if the drawn card
    happens to qualify for the permanent-put rider (e.g., Plains with
    MV 0 when you control 0 lands) it lands on the battlefield rather
    than in hand. Either way the library decreases by 1."""
    state = _new_state()
    _stock_library(state, 0, 2)
    AnticausalVestigeLeavesEffect().resolve(state, 0, ())
    p = state.players[0]
    assert len(p.library) == 1
    # The drawn Plains ended up either in hand or on battlefield.
    plains_count = sum(
        1 for c in p.hand + state.battlefield
        if c.printing.name == "Plains" and c.controller_id == 0
    )
    assert plains_count == 1


# -----------------------
# Integration
# -----------------------


def test_vestige_leaves_battlefield_fires_trigger():
    state = _new_state()
    _stock_library(state, 0, 2)
    vestige = state.new_object(
        EOE_CREATURES["Anticausal Vestige"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(vestige)
    lib_before = len(state.players[0].library)
    destroy(state, vestige)
    drain_stack(state)
    # Leaves trigger fired; at minimum library is smaller by one card
    # (drawn, then possibly put onto battlefield per the rider).
    assert len(state.players[0].library) == lib_before - 1


def test_vestige_printing_has_leaves_trigger_and_warp():
    v = EOE_CREATURES["Anticausal Vestige"]
    assert v.warp_cost_str == "{4}"
    triggers = {ab.trigger for ab in v.triggered_abilities}
    assert "leaves_battlefield" in triggers
