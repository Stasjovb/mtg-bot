"""Cube glue bucket: turn-loop hooks -- "at the beginning of your first
main phase" (Coalition Relic), delayed "your next main phase" triggers
(Mana Drain) -- exercised through BOTH turn loops (``simulate.run_step``
and the search adapter's ``_enter_step``)."""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.actions import PassPriority, resolve_top_of_stack
from mtg_bot.cards.base import make_sorcery
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.cube_glue import (
    CounterThenDelayedManaEqualToMV,
    RemoveAllCountersAddManaPerCounter,
)
from mtg_bot.game import StackItem, Zone
from mtg_bot.simulate import run_step
from mtg_bot.turn import Step

from tests._cube_glue_helpers import ScriptedAgent, arena, pool_colors, printing, put


@dataclass
class _PassAgent(ScriptedAgent):
    def choose_action(self, state, player_id, legal):
        return PassPriority()


def _passing_arena(active=0):
    s = arena(active=active)
    for p in s.players:
        p.agent = _PassAgent()
    return s


def _relic(s, pid=0, charge=2):
    relic = put(s, printing("Coalition Relic"), pid)
    relic.charge_counters = charge
    return relic


def test_coalition_relic_parse_shape():
    from mtg_bot.effects.predicates import Event

    p = printing("Coalition Relic")
    (trig,) = p.triggered_abilities
    assert trig.event == Event.BEGINNING_OF_PRECOMBAT_MAIN
    assert isinstance(trig.effect, RemoveAllCountersAddManaPerCounter)
    assert "first main phase" in trig.describe()


def test_coalition_relic_first_main_phase_trigger_via_simulate():
    s = _passing_arena()
    relic = _relic(s)
    run_step(s, Step.PRECOMBAT_MAIN)
    assert relic.charge_counters == 0
    assert pool_colors(s, 0) == ["any", "any"]


def test_coalition_relic_only_on_its_controllers_first_main():
    s = _passing_arena(active=1)
    relic = _relic(s, 0)
    run_step(s, Step.PRECOMBAT_MAIN)
    assert relic.charge_counters == 2
    s2 = _passing_arena()
    relic2 = _relic(s2, 0)
    run_step(s2, Step.POSTCOMBAT_MAIN)
    assert relic2.charge_counters == 2


def test_coalition_relic_no_counters_adds_nothing():
    s = _passing_arena()
    _relic(s, charge=0)
    run_step(s, Step.PRECOMBAT_MAIN)
    assert pool_colors(s, 0) == []


def test_first_main_trigger_via_search_adapter():
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter

    s = _passing_arena()
    _relic(s)
    adapter = MtgGameStateAdapter(s)
    state = adapter.engine_state
    assert any(
        isinstance(item.ability.effect, RemoveAllCountersAddManaPerCounter)
        for item in state.stack if item.ability is not None
    )


# ---------------------------------------------------------------------------
# Mana Drain
# ---------------------------------------------------------------------------

_ANCESTRAL = make_sorcery("Divination", "{2}{U}", DrawCards(amount=2))


def _drain(s, caster=0, x_spell=None):
    """P1's spell on the stack, then P0's Mana Drain targeting it."""
    spell = x_spell or _ANCESTRAL
    victim = s.new_object(spell, 1 - caster, Zone.STACK)
    s.stack.append(StackItem(source=victim, controller_id=1 - caster))
    drain = s.new_object(printing("Mana Drain"), caster, Zone.STACK)
    s.stack.append(StackItem(
        source=drain, controller_id=caster, targets=(("stack", 0),),
    ))
    resolve_top_of_stack(s)
    return victim


def test_mana_drain_parse_shape():
    eff = printing("Mana Drain").spell_effect
    assert isinstance(eff, CounterThenDelayedManaEqualToMV)
    assert eff.color == "C" and eff.target_count_range() == (1, 1)
    assert "next main phase" in eff.describe()


def test_mana_drain_counters_and_pays_out_at_next_main_phase():
    s = _passing_arena(active=1)
    victim = _drain(s)
    assert s.stack[-1].countered
    resolve_top_of_stack(s)
    assert victim in s.players[1].graveyard
    assert [d["step"] for d in s.delayed_triggers] == ["main"]
    # Not the opponent's main phase...
    run_step(s, Step.POSTCOMBAT_MAIN)
    assert pool_colors(s, 0) == []
    # ...but the caster's next one.
    s.active_player_idx = 0
    run_step(s, Step.PRECOMBAT_MAIN)
    assert pool_colors(s, 0) == ["C", "C", "C"]
    assert s.delayed_triggers == []


def test_mana_drain_in_first_main_pays_out_in_second_main():
    s = _passing_arena(active=0)
    _drain(s)
    run_step(s, Step.POSTCOMBAT_MAIN)
    assert pool_colors(s, 0) == ["C", "C", "C"]


def test_mana_drain_counts_x_and_skips_uncountered_spells():
    from mtg_bot.cards.base import make_instant

    s = _passing_arena(active=1)
    fireball = make_instant("Blaze", "{X}{R}", DrawCards(amount=1))
    victim = s.new_object(fireball, 1, Zone.STACK)
    s.stack.append(StackItem(source=victim, controller_id=1, x_value=4))
    drain = s.new_object(printing("Mana Drain"), 0, Zone.STACK)
    s.stack.append(StackItem(
        source=drain, controller_id=0, targets=(("stack", 0),),
    ))
    resolve_top_of_stack(s)
    assert s.delayed_triggers[0]["effect"].produces == (("C", 5),)
    # Target gone -> nothing countered, no delayed trigger.
    s2 = _passing_arena(active=1)
    drain2 = s2.new_object(printing("Mana Drain"), 0, Zone.STACK)
    s2.stack.append(StackItem(
        source=drain2, controller_id=0, targets=(("stack", 5),),
    ))
    resolve_top_of_stack(s2)
    assert s2.delayed_triggers == []


def test_mana_drain_delayed_trigger_via_search_adapter():
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter

    s = _passing_arena(active=1)
    _drain(s)
    resolve_top_of_stack(s)
    s.active_player_idx = 0
    s.priority_player_idx = 0
    s.step = Step.PRECOMBAT_MAIN
    adapter = MtgGameStateAdapter(s)
    state = adapter.engine_state
    assert state.delayed_triggers == []
    assert state.stack and state.stack[-1].ability is not None
