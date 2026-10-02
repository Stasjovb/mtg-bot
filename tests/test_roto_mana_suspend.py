"""Vintage Roto P3: Suspend (CR 702.62) and cards with no mana cost
(Lotus Bloom)."""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.base import make_creature, parse_mana_cost
from mtg_bot.cards.parser.roto_mana import split_roto_card_lines
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers

from tests._roto_helpers import arena, printing, put, roto_card, to_hand


def _upkeep(state, active=0):
    state.active_player_idx = active
    state.priority_player_idx = active
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    state.step = Step.PRECOMBAT_MAIN


def test_lotus_bloom_parses_suspend_and_has_no_mana_cost():
    pr = printing("Lotus Bloom")
    assert (pr.suspend_count, pr.suspend_cost_str) == (3, "{0}")
    assert pr.has_no_mana_cost
    assert pr.activated_abilities  # the sacrifice-for-mana ability


def test_lotus_bloom_can_only_be_suspended_not_cast():
    s = arena()
    bloom = to_hand(s, printing("Lotus Bloom"), 0)
    acts = legal_actions(s, 0)
    assert CastSpell(bloom.id) not in acts
    assert CastSpell(bloom.id, cast_for_free=True) not in acts
    assert CastSpell(bloom.id, use_suspend=True) in acts
    s.step = Step.UPKEEP  # an artifact without flash: sorcery timing only
    assert CastSpell(bloom.id, use_suspend=True) not in legal_actions(s, 0)


def test_lotus_bloom_suspends_and_is_cast_free_after_three_upkeeps():
    s = arena()
    bloom = to_hand(s, printing("Lotus Bloom"), 0)
    apply_action(s, 0, CastSpell(bloom.id, use_suspend=True))
    assert bloom in s.players[0].exile and bloom.time_counters == 3
    assert rm.is_suspended(bloom)
    assert s.players[0].spells_cast_this_turn == 0  # not a cast
    _upkeep(s, active=1)  # the opponent's upkeep: nothing happens
    assert bloom.time_counters == 3
    _upkeep(s)
    _upkeep(s)
    assert bloom.time_counters == 1 and bloom in s.players[0].exile
    _upkeep(s)
    assert bloom in s.battlefield
    assert s.players[0].spells_cast_this_turn == 1


def test_declining_the_free_cast_leaves_the_card_exiled():
    s = arena()
    bloom = to_hand(s, printing("Lotus Bloom"), 0)
    apply_action(s, 0, CastSpell(bloom.id, use_suspend=True))
    s.players[0].agent.yes = False
    for _ in range(3):
        _upkeep(s)
    assert bloom in s.players[0].exile
    assert bloom.time_counters == 0 and not rm.is_suspended(bloom)
    _upkeep(s)  # no longer suspended: no more triggers
    assert bloom in s.players[0].exile


def test_suspended_creature_gains_haste_when_cast():
    from mtg_bot.game import effective_keywords

    s = arena()
    beast = replace(
        make_creature("Slow Beast", "{5}", 5, 5),
        suspend_count=1, suspend_cost=parse_mana_cost("{0}"),
        suspend_cost_str="{0}",
    )
    card = to_hand(s, beast, 0)
    apply_action(s, 0, CastSpell(card.id, use_suspend=True))
    _upkeep(s)
    assert card in s.battlefield
    assert "haste" in effective_keywords(s, card)


def test_suspend_needs_the_cost_and_skips_cards_without_suspend():
    s = arena()
    gated = replace(
        make_creature("Pricey", "{5}", 5, 5),
        suspend_count=2, suspend_cost=parse_mana_cost("{R}"),
        suspend_cost_str="{R}",
    )
    card = to_hand(s, gated, 0)
    assert not rm.suspend_castable(s, 0, card, sorcery_timing=True)
    plain = to_hand(s, make_creature("Plain", "{1}", 1, 1), 0)
    assert not rm.suspend_castable(s, 0, plain, sorcery_timing=True)
    assert not rm.is_suspended(plain)


def test_time_counter_effects_guard_and_describe():
    s = arena()
    for eff in (
        rm.RemoveTimeCounterFromSuspendedSource(),
        rm.CastSuspendedSourceFree(),
    ):
        assert eff.describe()
        s.resolving_source = None
        eff.resolve(s, 0, ())
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    s.resolving_source = bear
    rm.CastSuspendedSourceFree().resolve(s, 0, ())  # not exiled
    rm.RemoveTimeCounterFromSuspendedSource().resolve(s, 0, ())
    assert bear in s.battlefield


def test_split_card_lines_paths():
    record, fields = split_roto_card_lines(roto_card("Lightning Bolt"))
    assert fields == {} and record == roto_card("Lightning Bolt")
    record, fields = split_roto_card_lines(roto_card("Lotus Bloom"))
    assert "Suspend" not in record["oracle_text"]
    assert fields["has_no_mana_cost"]
    land_record, land_fields = split_roto_card_lines(roto_card("Mountain"))
    assert land_fields == {}


def test_a_countered_suspended_creature_loses_its_haste_grant():
    from mtg_bot.actions import move_spell_off_stack

    s = arena()
    beast = replace(
        make_creature("Slow Beast", "{5}", 5, 5),
        suspend_count=1, suspend_cost=parse_mana_cost("{0}"),
        suspend_cost_str="{0}",
    )
    card = to_hand(s, beast, 0)
    apply_action(s, 0, CastSpell(card.id, use_suspend=True))
    s.active_player_idx = 0
    s.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(s)
    from mtg_bot.actions import resolve_top_of_stack

    resolve_top_of_stack(s)  # remove the last counter
    resolve_top_of_stack(s)  # cast it (now on the stack)
    item = s.stack.pop()
    assert any(ce.target_id == card.id for ce in s.continuous_effects)
    move_spell_off_stack(s, item.source)  # countered
    assert card in s.players[0].graveyard
    assert not any(ce.target_id == card.id for ce in s.continuous_effects)
