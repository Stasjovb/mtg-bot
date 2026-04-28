"""Tests for Weftblade Enhancer's ETB +1/+1 counter on each of up to two
target creatures."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import PutPlusOneCounterOnEachOfUpToNTargetCreatures
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# Effect-level
# -----------------------


def test_effect_target_count_range_and_describe():
    e = PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)
    assert e.requires_target()
    assert e.target_count_range() == (0, 2)
    assert "+1/+1" in e.describe()
    assert "2" in e.describe()


def test_effect_resolve_on_two_creatures():
    state = _new_state()
    a = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(a)
    b = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(b)
    PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2).resolve(
        state, 0, (("creature", a.id), ("creature", b.id)),
    )
    assert a.plus_one_counters == 1
    assert b.plus_one_counters == 1


def test_effect_ignores_wrong_kind_and_missing_ids():
    state = _new_state()
    a = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(a)
    PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2).resolve(
        state, 0, (
            ("player", 0),
            ("creature", 99999),
            ("creature", a.id),
        ),
    )
    assert a.plus_one_counters == 1


def test_effect_legal_targets_is_all_creatures():
    state = _new_state()
    mine = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mine)
    theirs = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(theirs)
    legal = PutPlusOneCounterOnEachOfUpToNTargetCreatures().legal_targets(
        state, 0,
    )
    ids = {tid for _, tid in legal}
    assert mine.id in ids and theirs.id in ids


# -----------------------
# Weftblade Enhancer integration
# -----------------------


def test_weftblade_etb_puts_counters_on_two_creatures():
    state = _new_state(_PickFirstAgent())
    a = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(a)
    b = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(b)
    wb = state.new_object(
        _PRINTINGS["Weftblade Enhancer"], 0, Zone.HAND,
    )
    put_into_battlefield(state, wb, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Two counters distributed. PickFirst always picks first legal, so
    # targets are a then b (after a is removed from remaining).
    total = a.plus_one_counters + b.plus_one_counters + wb.plus_one_counters
    assert total == 2


def test_weftblade_printing_has_warp_and_etb():
    w = _PRINTINGS["Weftblade Enhancer"]
    assert w.warp_cost_str == "{2}{W}"
    triggers = {_legacy_or_inferred_key(ab) for ab in w.triggered_abilities}
    assert "etb" in triggers
