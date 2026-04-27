"""Tests for Terrapact Intimidator's ETB opponent-choice effect."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES
from mtg_bot.effects import TerrapactIntimidatorETBEffect
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickOpponentAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        for kind, tid in legal_targets:
            if kind == "player" and tid != player_id:
                return (kind, tid)
        return legal_targets[0] if legal_targets else None


class _OpponentPicksLanders(_PickOpponentAgent):
    def choose_mode(self, state, player_id, mode_descriptions):
        return 0  # elect Landers


class _OpponentDeclines(_PickOpponentAgent):
    def choose_mode(self, state, player_id, mode_descriptions):
        return 1  # decline → controller gets counters


def _new_state(p0_agent, p1_agent):
    state = GameState()
    state.players.append(Player(id=0, agent=p0_agent))
    state.players.append(Player(id=1, agent=p1_agent))
    return state


# -----------------------
# Effect-level
# -----------------------


def test_effect_requires_target_and_legal_targets_opponent_only():
    state = _new_state(_PickOpponentAgent(), _PickOpponentAgent())
    e = TerrapactIntimidatorETBEffect()
    assert e.requires_target()
    legal = e.legal_targets(state, 0)
    assert legal == [("player", 1)]


def test_effect_describe_covers_both_branches():
    d = TerrapactIntimidatorETBEffect().describe()
    assert "Lander" in d
    assert "+1/+1" in d


def test_effect_no_target_is_noop():
    state = _new_state(_PickOpponentAgent(), _PickOpponentAgent())
    TerrapactIntimidatorETBEffect().resolve(state, 0, ())


def test_effect_wrong_target_kind_is_noop():
    state = _new_state(_PickOpponentAgent(), _PickOpponentAgent())
    TerrapactIntimidatorETBEffect().resolve(state, 0, (("creature", 1),))


# -----------------------
# Terrapact Intimidator integration
# -----------------------


def test_terrapact_etb_opponent_elects_landers():
    state = _new_state(_OpponentPicksLanders(), _OpponentPicksLanders())
    tp = state.new_object(
        EOE_CREATURES["Terrapact Intimidator"], 0, Zone.HAND,
    )
    state.players[0].hand.append(tp)
    put_into_battlefield(state, tp, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Two Landers under controller 0.
    landers = [
        o for o in state.battlefield
        if o.printing.name == "Lander" and o.controller_id == 0
    ]
    assert len(landers) == 2
    # No extra counters on Terrapact.
    assert tp.plus_one_counters == 0


def test_terrapact_etb_opponent_declines_gives_two_counters():
    state = _new_state(_OpponentDeclines(), _OpponentDeclines())
    tp = state.new_object(
        EOE_CREATURES["Terrapact Intimidator"], 0, Zone.HAND,
    )
    state.players[0].hand.append(tp)
    put_into_battlefield(state, tp, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    assert tp.plus_one_counters == 2
    assert not any(
        o.printing.name == "Lander" for o in state.battlefield
    )


def test_terrapact_printing_has_etb():
    t = EOE_CREATURES["Terrapact Intimidator"]
    triggers = {_legacy_or_inferred_key(ab) for ab in t.triggered_abilities}
    assert "etb" in triggers
