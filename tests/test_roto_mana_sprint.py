"""Vintage Roto P3: Grim Reaper's Sprint (Morbid cost reduction, an
Aura granting +2/+2 and haste, untap + an additional combat phase)."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    apply_cost_reductions,
    drain_stack,
)
from mtg_bot.cards.base import make_basic_land, make_creature, parse_mana_cost
from mtg_bot.cards.parser.roto_mana import parse_roto_cost_reduction_line
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import effective_keywords, effective_power
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, next_step

from tests._roto_helpers import arena, printing, put, to_hand

MOUNTAIN = make_basic_land("Mountain", "R")
SPRINT = "Grim Reaper's Sprint"


def _cast_sprint(step=Step.PRECOMBAT_MAIN, lands=5):
    s = arena()
    s.step = step
    for _ in range(lands):
        put(s, MOUNTAIN, 0)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0, tapped=True)
    sprint = to_hand(s, printing(SPRINT), 0)
    s.players[0].agent.targets = [("creature", bear.id)]
    apply_action(s, 0, CastSpell(sprint.id))
    drain_stack(s)
    return s, bear, sprint


def test_sprint_costs_three_less_after_a_creature_died():
    s = arena()
    pr = printing(SPRINT)
    assert apply_cost_reductions(pr, s, 0, pr.mana_cost) == pr.mana_cost
    s.creatures_died_this_turn = 1
    reduced = apply_cost_reductions(pr, s, 0, pr.mana_cost)
    assert reduced.total == 2
    for _ in range(2):
        put(s, MOUNTAIN, 0)
    put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    card = to_hand(s, pr, 0)
    assert CastSpell(card.id) in legal_actions(s, 0)


def test_sprint_enchants_untaps_and_adds_a_combat_in_the_first_main():
    s, bear, sprint = _cast_sprint()
    assert sprint.attached_to == bear.id
    assert effective_power(s, bear) == 4
    assert "haste" in effective_keywords(s, bear)
    assert not bear.tapped  # untapped by the enters trigger
    assert s.extra_combat_phases == 1


def test_sprint_in_the_second_main_adds_a_combat_then_the_end_step():
    s, bear, _ = _cast_sprint(step=Step.POSTCOMBAT_MAIN)
    assert s.extra_combat_phases == 0
    assert next_step(s, Step.POSTCOMBAT_MAIN) == Step.BEGINNING_OF_COMBAT
    assert next_step(s, Step.END_OF_COMBAT) == Step.END
    # Consumed: the next turn's structure is normal.
    assert next_step(s, Step.POSTCOMBAT_MAIN) == Step.END
    assert next_step(s, Step.END_OF_COMBAT) == Step.POSTCOMBAT_MAIN


def test_extra_combat_only_in_your_main_phase():
    s = arena()
    s.step = Step.BEGINNING_OF_COMBAT
    rm.AdditionalCombatAfterThisMainPhase().resolve(s, 0, ())
    assert s.extra_combat_phases == 0
    s.step = Step.PRECOMBAT_MAIN
    rm.AdditionalCombatAfterThisMainPhase().resolve(s, 1, ())  # not P1's turn
    assert s.extra_combat_phases == 0
    assert "main phase" in rm.AdditionalCombatAfterThisMainPhase().describe()
    assert rm.roto_next_step(s, Step.POSTCOMBAT_MAIN) is None


def test_morbid_grammar_paths():
    line = parse_roto_cost_reduction_line(
        "Morbid — This spell costs {3} less to cast if a creature died "
        "this turn."
    )
    assert line.amount == 3
    assert parse_roto_cost_reduction_line(
        "This spell costs {2} less to cast if frobs."
    ) is None
    assert parse_mana_cost("{4}{R}").total == 5
