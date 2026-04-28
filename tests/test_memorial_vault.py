"""Tests for Memorial Vault — strict "Sacrifice another artifact"
activation cost + X-from-sacrificed-artifact-mana-value resolve."""

from mtg_bot.actions import (
    ActivateAbility,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import ActivationCost, MemorialVaultActivatedEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(num_mountains: int = 0):
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    for _ in range(num_mountains):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _stock_library(state, owner_id, n):
    """Fill controller's library with n known cards (Mountains)."""
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Mountain"], owner_id, Zone.LIBRARY)
        state.players[owner_id].library.append(c)


# -----------------------
# Cost filter regression
# -----------------------


def test_activation_illegal_when_only_creatures_present():
    """Strict artifact filter: a sole creature on board cannot pay
    the sac cost (the previous wider 'creature_or_artifact' cost
    incorrectly accepted creatures)."""
    state = _new_state(num_mountains=4)
    state.step = Step.PRECOMBAT_MAIN
    vault = _put(state, _PRINTINGS["Memorial Vault"])
    vault.summoning_sick = False
    # Only the Vault itself + a creature (no other artifacts).
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bear.summoning_sick = False
    acts = [a for a in legal_actions(state, 0) if isinstance(a, ActivateAbility)]
    assert acts == []


def test_activation_illegal_when_only_lands_present():
    """Lands also cannot pay the artifact-only sac cost."""
    state = _new_state(num_mountains=4)
    state.step = Step.PRECOMBAT_MAIN
    vault = _put(state, _PRINTINGS["Memorial Vault"])
    vault.summoning_sick = False
    # Mountains are lands, not artifacts — cannot satisfy the cost.
    acts = [a for a in legal_actions(state, 0) if isinstance(a, ActivateAbility)]
    assert acts == []


def test_activation_legal_with_another_artifact():
    """A second artifact on the battlefield satisfies the cost."""
    state = _new_state(num_mountains=4)
    state.step = Step.PRECOMBAT_MAIN
    vault = _put(state, _PRINTINGS["Memorial Vault"])
    vault.summoning_sick = False
    block = _put(state, _PRINTINGS["Nutrient Block"])  # MV 1 artifact
    block.summoning_sick = False
    acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, ActivateAbility) and a.source_id == vault.id
    ]
    assert len(acts) == 1


# -----------------------
# Resolution: X = 1 + sacrificed artifact's mana value
# -----------------------


def test_resolve_exiles_x_equals_one_plus_sacrificed_mv():
    """Sacrificing an MV-3 artifact means X = 4 cards exiled, all of
    which become playable from exile this turn."""
    state = _new_state(num_mountains=4)
    state.step = Step.PRECOMBAT_MAIN
    vault = _put(state, _PRINTINGS["Memorial Vault"])
    vault.summoning_sick = False
    starcage = _put(state, _PRINTINGS["Pinnacle Starcage"])  # MV 3
    starcage.summoning_sick = False
    _stock_library(state, 0, 6)

    # PickFirstAgent will choose the single legal sac (the only other
    # artifact = Pinnacle Starcage, MV 3). Expected X = 1 + 3 = 4.
    acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, ActivateAbility) and a.source_id == vault.id
    ]
    assert acts, "expected Memorial Vault activation to be legal"
    apply_action(state, 0, acts[0])
    resolve_top_of_stack(state)

    # Starcage went to graveyard, Vault tapped, 4 cards exiled.
    assert starcage in state.players[0].graveyard
    assert vault.tapped
    assert len(state.players[0].exile) == 4
    for ex in state.players[0].exile:
        assert ex.playable_from_exile_this_turn is True


def test_describe_mentions_x_and_play_clause():
    desc = MemorialVaultActivatedEffect().describe()
    assert "X" in desc
    assert "play those cards" in desc


def test_activation_cost_describe_includes_sacrifice_another_artifact():
    c = ActivationCost(tap_self=True, sacrifice_another_artifact=True)
    text = c.describe()
    assert "Sacrifice another artifact" in text
