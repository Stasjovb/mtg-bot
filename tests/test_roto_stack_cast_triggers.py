"""Roto P1 cast triggers: Chalice of the Void, Eidolon of the Great
Revel, Esper Sentinel, Mystic Remora (and cumulative upkeep), Vexing
Bauble, Nether Void (and the world rule), Aetherflux Reservoir."""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_creature, parse_mana_cost
from mtg_bot.cards.parser.roto_stack import parse_roto_stack_line
from mtg_bot.effects.generic.roto_stack import (
    CastersNoncreatureSpellsThisTurnIs,
    CounterEventSpell,
    CumulativeUpkeep,
    DrawUnlessCasterPays,
    GainLifePerSpellYouCastThisTurn,
    NoManaSpentToCast,
    SourceDealsDamageToCaster,
    SpellManaValueAtMost,
    SpellManaValueEqualsSourceCounters,
)
from mtg_bot.game import Zone
from mtg_bot.roto_restrictions import apply_world_rule
from mtg_bot.turn import run_beginning_of_upkeep_triggers, state_based_actions

from tests._roto_helpers import agent, arena, printing, put, to_hand, to_library


def _lands(state, name, n, pid=0):
    return [put(state, printing(name), pid) for _ in range(n)]


def _cast(state, pid, card, **kw):
    state.priority_player_idx = pid
    apply_action(state, pid, CastSpell(card.id, **kw))


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


def _bolt(state, pid=1, target=("player", 0)):
    bolt = to_hand(state, printing("Lightning Bolt"), pid)
    _lands(state, "Mountain", 1, pid)
    agent(state, pid).targets = [target]
    _cast(state, pid, bolt)
    return bolt


def _enter(state, name, pid=0, x=0):
    """Cast-resolve shortcut: put ``name`` onto the battlefield as the
    resolving spell with X = ``x``."""
    card = to_hand(state, printing(name), pid)
    state.players[pid].hand.remove(card)
    card.zone = Zone.STACK
    state.resolving_spell = card
    state.resolving_x_value = x
    put_into_battlefield(state, card, pid)
    state.resolving_spell = None
    state.resolving_x_value = 0
    card.summoning_sick = False
    return card


# ---------------------------------------------------------------------
# Eidolon of the Great Revel
# ---------------------------------------------------------------------


def test_eidolon_hits_the_caster_of_a_cheap_spell():
    state = arena(active=1)
    put(state, printing("Eidolon of the Great Revel"), 0)
    _bolt(state)
    assert state.stack[-1].ability is not None  # the trigger
    _drain(state)
    assert state.players[1].life == 18  # Eidolon's 2
    assert state.players[0].life == 17  # the Bolt


def test_eidolon_ignores_expensive_spells_and_counts_x():
    state = arena(active=1)
    put(state, printing("Eidolon of the Great Revel"), 0)
    big = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, big)  # mana value 2: triggers
    assert len(state.stack) == 2
    _drain(state)
    assert state.players[1].life == 18
    pred = SpellManaValueAtMost(3)
    xspell = replace(printing("Lightning Bolt"), mana_cost=parse_mana_cost("{X}{R}"))
    _bolt(state)
    item = next(i for i in state.stack if i.ability is None)
    item.source.printing = xspell
    item.x_value = 4
    assert not pred.test(item.source, state)
    assert not pred.test(object(), state)


# ---------------------------------------------------------------------
# Chalice of the Void
# ---------------------------------------------------------------------


def test_chalice_enters_with_x_counters_and_counters_matching_spells():
    state = arena(active=1)
    chalice = _enter(state, "Chalice of the Void", 0, x=1)
    assert chalice.charge_counters == 1
    bolt = _bolt(state)
    _drain(state)
    assert bolt in state.players[1].graveyard
    assert state.players[0].life == 20
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, goyf)
    assert len(state.stack) == 1  # mana value 2: no trigger
    _drain(state)
    assert goyf in state.battlefield


def test_chalice_put_onto_battlefield_has_no_counters():
    state = arena(active=1)
    chalice = put(state, printing("Chalice of the Void"), 0)
    put_into_battlefield(state, to_hand(state, printing("Chalice of the Void"), 1), 1)
    assert chalice.charge_counters == 0
    pred = SpellManaValueEqualsSourceCounters()
    assert not pred.matches(state, {}, chalice)


def test_chalice_casting_with_x_pays_twice_x():
    state = arena(active=0)
    chalice = to_hand(state, printing("Chalice of the Void"))
    _lands(state, "Island", 4)
    agent(state, 0).x_value = 2
    _cast(state, 0, chalice)
    _drain(state)
    on_bf = next(o for o in state.battlefield if o.printing.name == "Chalice of the Void")
    assert on_bf.charge_counters == 2
    assert all(o.tapped for o in state.battlefield if o.printing.name == "Island")


# ---------------------------------------------------------------------
# Vexing Bauble
# ---------------------------------------------------------------------


def test_vexing_bauble_counters_spells_cast_without_mana():
    state = arena(active=1)
    put(state, printing("Vexing Bauble"), 0)
    # Mental Misstep paid with 2 life: no mana spent.
    misstep = to_hand(state, printing("Mental Misstep"), 1)
    agent(state, 1).yes = True
    target_bolt = _bolt(state, pid=0, target=("player", 1))
    state.active_player_idx = 1
    agent(state, 1).targets = [("stack", 0)]
    _cast(state, 1, misstep)
    assert misstep.mana_spent_to_cast == 0
    assert target_bolt.mana_spent_to_cast == 1
    _drain(state)
    assert any("Mental Misstep is countered" in line for line in state.log)
    assert state.players[1].life == 15  # the Bolt still resolved


def test_vexing_bauble_lets_paid_spells_resolve():
    state = arena(active=1)
    put(state, printing("Vexing Bauble"), 0)
    _bolt(state)
    assert len(state.stack) == 1
    assert not NoManaSpentToCast().test(object(), state)


# ---------------------------------------------------------------------
# Esper Sentinel
# ---------------------------------------------------------------------


def test_esper_sentinel_taxes_the_first_noncreature_spell():
    state = arena(active=1)
    put(state, printing("Esper Sentinel"), 0)
    to_library(state, printing("Island"), 0)
    _bolt(state)
    # The opponent has no spare mana for {1}: Sentinel's controller draws.
    _drain(state)
    assert len(state.players[0].hand) == 1
    # Second noncreature spell this turn: no trigger.
    _bolt(state)
    assert len(state.stack) == 1
    _drain(state)


def test_esper_sentinel_caster_may_pay():
    state = arena(active=1)
    put(state, printing("Esper Sentinel"), 0)
    to_library(state, printing("Island"), 0)
    _lands(state, "Mountain", 1, 1)  # spare mana for the {1}
    _bolt(state)
    _drain(state)
    assert not state.players[0].hand
    assert any("pays {1}" in line for line in state.log)


def test_esper_sentinel_ignores_creature_spells_and_own_spells():
    state = arena(active=1)
    put(state, printing("Esper Sentinel"), 0)
    goyf = to_hand(state, printing("Tarmogoyf"), 1)
    _lands(state, "Forest", 2, 1)
    _cast(state, 1, goyf)
    assert len(state.stack) == 1
    _drain(state)
    state.active_player_idx = 0
    _bolt(state, pid=0, target=("player", 1))
    assert len(state.stack) == 1
    assert not CastersNoncreatureSpellsThisTurnIs(1).matches(state, {}, None)


# ---------------------------------------------------------------------
# Mystic Remora + cumulative upkeep
# ---------------------------------------------------------------------


def test_mystic_remora_draws_unless_the_caster_pays_four():
    state = arena(active=1)
    put(state, printing("Mystic Remora"), 0)
    to_library(state, printing("Island"), 0)
    to_library(state, printing("Island"), 0)
    _bolt(state)
    _drain(state)
    assert len(state.players[0].hand) == 1
    # With four spare mana the opponent pays instead.
    _lands(state, "Mountain", 4, 1)
    _bolt(state)
    _drain(state)
    assert len(state.players[0].hand) == 1
    assert any("pays {4}" in line for line in state.log)


def test_mystic_remora_draw_is_optional():
    state = arena(active=1)
    put(state, printing("Mystic Remora"), 0)
    to_library(state, printing("Island"), 0)
    agent(state, 0).yes = False
    _bolt(state)
    _drain(state)
    assert not state.players[0].hand


def test_cumulative_upkeep_grows_and_sacrifices_when_unpaid():
    state = arena(active=0)
    remora = put(state, printing("Mystic Remora"), 0)
    _lands(state, "Island", 1)
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert remora in state.battlefield
    from mtg_bot.game import named_counter_count

    assert named_counter_count(remora, "age") == 1
    for o in state.battlefield:
        o.tapped = False
    # Two age counters -> {2}; only one Island.
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert remora not in state.battlefield
    assert remora in state.players[0].graveyard


def test_cumulative_upkeep_declined_and_gone_source():
    state = arena(active=0)
    remora = put(state, printing("Mystic Remora"), 0)
    _lands(state, "Island", 1)
    agent(state, 0).yes = False
    run_beginning_of_upkeep_triggers(state)
    _drain(state)
    assert remora not in state.battlefield
    eff = CumulativeUpkeep()
    state.resolving_source = None
    eff.resolve(state, 0, ())
    assert "cumulative upkeep" in eff.describe()


# ---------------------------------------------------------------------
# Nether Void + the world rule
# ---------------------------------------------------------------------


def test_nether_void_taxes_every_spell():
    state = arena(active=1)
    put(state, printing("Nether Void"), 0)
    bolt = _bolt(state)
    _drain(state)
    assert bolt in state.players[1].graveyard
    assert state.players[0].life == 20
    _lands(state, "Mountain", 3, 1)
    _bolt(state)
    _drain(state)
    assert state.players[0].life == 17


def test_world_rule_keeps_the_newest_world():
    state = arena()
    old = put(state, printing("Nether Void"), 0)
    old.etb_timestamp = 1
    new = put(state, printing("Nether Void"), 1)
    new.etb_timestamp = 2
    assert state_based_actions(state)
    assert old in state.players[0].graveyard and new in state.battlefield
    assert not apply_world_rule(state)
    # Same timestamp: both go.
    a = put(state, printing("Nether Void"), 0)
    a.etb_timestamp = new.etb_timestamp
    assert apply_world_rule(state)
    assert a not in state.battlefield and new not in state.battlefield


# ---------------------------------------------------------------------
# Aetherflux Reservoir
# ---------------------------------------------------------------------


def test_aetherflux_gains_life_per_spell_this_turn():
    state = arena(active=0)
    put(state, printing("Aetherflux Reservoir"), 0)
    _bolt(state, pid=0, target=("player", 1))
    _drain(state)
    assert state.players[0].life == 21
    _bolt(state, pid=0, target=("player", 1))
    _drain(state)
    assert state.players[0].life == 23
    eff = GainLifePerSpellYouCastThisTurn()
    state.players[0].spells_cast_this_turn = 0
    eff.resolve(state, 0, ())
    assert state.players[0].life == 23
    assert "each spell" in eff.describe()


# ---------------------------------------------------------------------
# Effects and grammar edges
# ---------------------------------------------------------------------


def test_cast_event_effects_edges():
    state = arena(active=1)
    eff = CounterEventSpell(unless_pays="{1}")
    state.resolving_event_subject_id = -1
    eff.resolve(state, 0, ())
    assert "unless that player pays {1}" in eff.describe()
    assert CounterEventSpell().describe() == "counter that spell"
    dmg = SourceDealsDamageToCaster(amount=2)
    dmg.resolve(state, 0, ())
    assert dmg.targets_from_event(state, {}) == ()
    assert dmg.event_subject_id({}) == -1
    assert "2 damage" in dmg.describe()
    draw = DrawUnlessCasterPays(cost="{4}", optional=True)
    assert draw.describe().startswith("you may draw")
    assert "power" in DrawUnlessCasterPays(cost_is_source_power=True).describe()
    # An uncounterable spell isn't countered by the trigger.
    goodbye = to_hand(state, printing("Long Goodbye"), 1)
    _lands(state, "Swamp", 2, 1)
    victim = put(state, make_creature("Bear", "{1}{G}", 2, 2), 0)
    agent(state, 1).targets = [("creature", victim.id)]
    _cast(state, 1, goodbye)
    state.resolving_event_subject_id = goodbye.id
    CounterEventSpell().resolve(state, 0, ())
    assert not state.stack[0].countered


def test_source_power_uses_last_known_information():
    from mtg_bot.effects.generic.roto_stack import _source_power

    state = arena()
    state.resolving_source = None
    assert _source_power(state) == 0
    sentinel = to_hand(state, printing("Esper Sentinel"))
    state.resolving_source = sentinel
    assert _source_power(state) == 1


def test_cast_trigger_grammar_edges():
    card = {"name": "X"}
    for line in (
        "Whenever a player casts a wombat spell, counter that spell.",
        "Whenever a player casts their first noncreature spell each turn, counter that spell.",
        "Whenever an opponent casts their first creature spell each turn, counter that spell.",
        "Whenever a player casts a spell, if no mana was spent to cast it, draw a card.",
        "Whenever a player casts a spell, frobnicate.",
        "Whenever a player casts the spell, counter that spell.",
    ):
        assert parse_roto_stack_line(line, card) is None, line
    ok = parse_roto_stack_line(
        "Whenever a player casts a noncreature spell with mana value 2 or "
        "less, draw a card unless that player pays {2}.", card,
    )
    assert ok is not None
    assert parse_roto_stack_line("Cumulative upkeep {W}{W}", card) is not None
    assert parse_roto_stack_line("Cumulative upkeep—Pay 1 life.", card) is None
