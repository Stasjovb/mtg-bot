"""Cube spells-B: Splice onto Arcane (Goryo's Vengeance, Through the
Breach) and Through the Breach's haste + next-end-step sacrifice."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.alt_casting import offer_splices
from mtg_bot.cards import SYNTHETIC_CREATURES, parse_mana_cost
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import _casting_keyword_fields
from mtg_bot.effects.generic.cheat_into_play import (
    PutCreatureFromHandHasteSacrificeAtNextEndStep,
)
from mtg_bot.game import Zone, effective_keywords
from mtg_bot.turn import Step, run_delayed_end_step_triggers
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _creature(state, pid, name, zone):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, zone)
    p = state.player_by_id(pid)
    {Zone.HAND: p.hand, Zone.GRAVEYARD: p.graveyard}[zone].append(obj)
    return obj


def _legendary(state, pid, zone):
    import dataclasses

    obj = _creature(state, pid, "Great Wurm", zone)
    obj.printing = dataclasses.replace(
        obj.printing, supertypes=("Legendary",),
        type_line="Legendary Creature — Wurm",
    )
    return obj


def test_splice_printings(cube):
    goryo = cube["Goryo's Vengeance"]
    assert goryo.subtypes == ("Arcane",)
    assert goryo.type_line.startswith("Instant")
    assert goryo.splice_onto == "Arcane" and goryo.splice_cost_str == "{2}{B}"
    breach = cube["Through the Breach"]
    assert breach.splice_cost == parse_mana_cost("{2}{R}{R}")
    assert breach.spell_effect == PutCreatureFromHandHasteSacrificeAtNextEndStep()
    assert _casting_keyword_fields("Splice onto Arcane {1}{U}")["splice_onto"] == "Arcane"


def test_through_the_breach_haste_then_sacrifice():
    state = make_state()
    wurm = _creature(state, 0, "Great Wurm", Zone.HAND)
    breach = add(state, 0, "Through the Breach", Zone.HAND)
    add_lands(state, 0, "Mountain", 5)
    apply_action(state, 0, CastSpell(breach.id))
    resolve_top_of_stack(state)
    assert wurm in state.battlefield
    assert "haste" in effective_keywords(state, wurm)
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    resolve_top_of_stack(state)
    assert wurm in state.players[0].graveyard


def test_through_the_breach_decline_and_no_creature():
    state = make_state(agent0=ScriptedAgent(library=[None]))
    bear = _creature(state, 0, "Wild Bear", Zone.HAND)
    eff = PutCreatureFromHandHasteSacrificeAtNextEndStep()
    eff.resolve(state, 0)
    assert bear in state.players[0].hand
    eff.resolve(make_state(), 0)
    assert "sacrifice it" in eff.describe()


def test_goryos_with_spliced_through_the_breach():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    legend = _legendary(state, 0, Zone.GRAVEYARD)
    bear = _creature(state, 0, "Wild Bear", Zone.HAND)
    goryo = add(state, 0, "Goryo's Vengeance", Zone.HAND)
    breach = add(state, 0, "Through the Breach", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    add_lands(state, 0, "Mountain", 4)
    agent.scripts["target"] = [("graveyard_card", legend.id)]
    agent.scripts["library"] = [bear.id]
    apply_action(state, 0, CastSpell(goryo.id))
    item = state.stack[-1]
    assert len(item.spliced) == 1 and item.spliced[0][0].name == "Through the Breach"
    assert breach in state.players[0].hand  # spliced cards stay in hand
    assert all(l.tapped for l in state.battlefield if l.printing.is_land)
    resolve_top_of_stack(state)
    assert legend in state.battlefield and bear in state.battlefield
    assert "haste" in effective_keywords(state, bear)
    assert goryo in state.players[0].graveyard


def test_splice_declined_or_unaffordable():
    agent = ScriptedAgent(yes_no=[False])
    state = make_state(agent0=agent)
    legend = _legendary(state, 0, Zone.GRAVEYARD)
    goryo = add(state, 0, "Goryo's Vengeance", Zone.HAND)
    add(state, 0, "Through the Breach", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    add_lands(state, 0, "Mountain", 4)
    agent.scripts["target"] = [("graveyard_card", legend.id)]
    apply_action(state, 0, CastSpell(goryo.id))
    assert state.stack[-1].spliced == ()
    # Unaffordable: nothing is offered.
    state = make_state(agent0=ScriptedAgent())
    legend = _legendary(state, 0, Zone.GRAVEYARD)
    goryo = add(state, 0, "Goryo's Vengeance", Zone.HAND)
    add(state, 0, "Through the Breach", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    state.players[0].agent.scripts["target"] = [("graveyard_card", legend.id)]
    apply_action(state, 0, CastSpell(goryo.id))
    assert state.stack[-1].spliced == ()


def test_splice_needs_targets_for_the_spliced_effect():
    state = make_state()
    breach = add(state, 0, "Through the Breach", Zone.HAND)
    add(state, 0, "Goryo's Vengeance", Zone.HAND)  # no legendary in GY
    add_lands(state, 0, "Mountain", 5)
    add_lands(state, 0, "Swamp", 3)
    cost, spliced = offer_splices(
        state, 0, breach, breach.printing.mana_cost, frozenset({"spell"}),
    )
    assert spliced == () and cost == breach.printing.mana_cost
    # Non-subtyped spell / no agent: nothing offered.
    ritual = add(state, 0, "Dark Ritual", Zone.HAND)
    assert offer_splices(state, 0, ritual, ritual.printing.mana_cost, frozenset())[1] == ()
    state.players[0].agent = None
    assert offer_splices(state, 0, breach, breach.printing.mana_cost, frozenset())[1] == ()


def test_spliced_goryo_onto_breach_picks_target():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    legend = _legendary(state, 0, Zone.GRAVEYARD)
    breach = add(state, 0, "Through the Breach", Zone.HAND)
    add(state, 0, "Goryo's Vengeance", Zone.HAND)
    add_lands(state, 0, "Mountain", 5)
    add_lands(state, 0, "Swamp", 3)
    agent.scripts["target"] = [None]  # declines -> first legal target
    agent.scripts["library"] = [None]  # Breach itself puts nothing in
    apply_action(state, 0, CastSpell(breach.id))
    assert state.stack[-1].spliced[0][1] == (("graveyard_card", legend.id),)
    resolve_top_of_stack(state)
    assert legend in state.battlefield
