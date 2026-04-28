"""Legend rule SBA (CR 704.5j): if a player controls two or more
legendary permanents with the same name, that player chooses one to
keep; the rest go to their owners' graveyards.

The choice is exposed via the new ``Agent.choose_legend_keep``
callback. Default is "keep the first id" — concrete tests pass an
agent that picks deterministically.
"""

from __future__ import annotations

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, state_based_actions

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _KeepFirst(Agent):
    """Agent that keeps the first legendary in the group."""

    def choose_legend_keep(self, state, player_id, legend_object_ids):
        return legend_object_ids[0]


class _KeepLast(Agent):
    """Agent that keeps the last legendary in the group."""

    def choose_legend_keep(self, state, player_id, legend_object_ids):
        return legend_object_ids[-1]


def _new_state(agent_cls=_KeepFirst):
    state = GameState()
    state.players.append(Player(id=0, agent=agent_cls()))
    state.players.append(Player(id=1, agent=agent_cls()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_single_legendary_no_legend_rule():
    """One copy of a legendary doesn't trigger the SBA."""
    state = _new_state()
    tannuk = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    assert state_based_actions(state) is False
    assert tannuk in state.battlefield


def test_two_same_name_legendaries_one_goes_to_graveyard():
    """Two copies of Tannuk under one player's control: one is kept,
    the other goes to graveyard."""
    state = _new_state(agent_cls=_KeepFirst)
    t1 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    t2 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)

    state_based_actions(state)

    # _KeepFirst keeps t1 (lowest id), t2 goes to graveyard.
    assert t1 in state.battlefield
    assert t2 not in state.battlefield
    assert t2 in state.players[0].graveyard


def test_legend_rule_uses_agent_callback_for_choice():
    """The agent decides which to keep via choose_legend_keep."""
    state = _new_state(agent_cls=_KeepLast)
    t1 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    t2 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)

    state_based_actions(state)

    # _KeepLast keeps t2, t1 goes to graveyard.
    assert t2 in state.battlefield
    assert t1 not in state.battlefield
    assert t1 in state.players[0].graveyard


def test_three_same_name_legendaries_only_one_survives():
    """Three copies → two go to graveyard."""
    state = _new_state()
    t1 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    t2 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    t3 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)

    state_based_actions(state)

    survivors = [t for t in (t1, t2, t3) if t in state.battlefield]
    assert len(survivors) == 1
    assert survivors[0] is t1  # _KeepFirst


def test_two_players_each_with_their_own_legendary_no_rule():
    """The legend rule is per-controller. Each player can have one
    copy of the same legendary; no SBA fires."""
    state = _new_state()
    t1 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    t2 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 1)
    t2.controller_id = 1

    state_based_actions(state)

    assert t1 in state.battlefield
    assert t2 in state.battlefield


def test_two_players_each_controlling_two_copies_each_resolves_separately():
    """Each player owns two copies. Each player picks one to keep
    independently."""
    state = _new_state(agent_cls=_KeepFirst)
    a1 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    a2 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    b1 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 1)
    b1.controller_id = 1
    b2 = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 1)
    b2.controller_id = 1

    state_based_actions(state)

    # P0 keeps a1, P1 keeps b1.
    assert a1 in state.battlefield
    assert a2 not in state.battlefield
    assert b1 in state.battlefield
    assert b2 not in state.battlefield


def test_non_legendary_duplicates_no_legend_rule():
    """The rule is for LEGENDARY permanents only. Two non-legendary
    creatures with the same name don't trigger."""
    state = _new_state()
    b1 = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    b2 = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)

    state_based_actions(state)

    assert b1 in state.battlefield
    assert b2 in state.battlefield


def test_different_legendary_names_no_rule():
    """Two different legendaries (different names) are fine — even
    if one player controls both."""
    state = _new_state()
    tannuk = _put(state, _PRINTINGS["Tannuk, Steadfast Second"], 0)
    sami = _put(state, _PRINTINGS["Sami, Wildcat Captain"], 0)

    state_based_actions(state)

    assert tannuk in state.battlefield
    assert sami in state.battlefield
