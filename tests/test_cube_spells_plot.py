"""Cube spells-B: Plot (Pillage the Bog) — the plot special action from
hand and the free sorcery-speed cast from exile on a later turn."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards import parse_mana_cost
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import _casting_keyword_fields
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._spells_b_helpers import add, add_lands, make_state

BOG = "Pillage the Bog"


def test_plot_printing():
    p = OracleParserCardSource(pool="cube").get_printings()[BOG]
    assert p.plot_cost == parse_mana_cost("{1}{B}{G}")
    assert _casting_keyword_fields("Plot {2}") == {
        "plot_cost": parse_mana_cost("{2}"), "plot_cost_str": "{2}",
    }


def test_plot_then_cast_free_on_a_later_turn():
    state = make_state()
    for _ in range(6):
        add(state, 0, "Island", Zone.LIBRARY)
    bog = add(state, 0, BOG, Zone.HAND)
    add(state, 0, BOG, Zone.HAND)  # duplicate: one plot action offered
    add_lands(state, 0, "Swamp", 2)
    add_lands(state, 0, "Forest", 1)
    plots = [a for a in legal_actions(state, 0)
             if isinstance(a, CastSpell) and a.use_plot]
    assert plots == [CastSpell(bog.id, use_plot=True)]
    spells_before = state.players[0].spells_cast_this_turn
    apply_action(state, 0, CastSpell(bog.id, use_plot=True))
    assert bog in state.players[0].exile and bog.plotted_turn == state.turn_number
    assert state.stack == [] and state.players[0].spells_cast_this_turn == spells_before
    assert bog.publicly_known_to == frozenset({0, 1})
    # Not castable the same turn.
    assert CastSpell(bog.id, cast_for_free=True) not in legal_actions(state, 0)
    state.turn_number += 1
    for land in state.battlefield:
        land.tapped = True
    assert CastSpell(bog.id, cast_for_free=True) in legal_actions(state, 0)
    # Sorcery timing only.
    state.step = Step.UPKEEP
    assert CastSpell(bog.id, cast_for_free=True) not in legal_actions(state, 0)
    state.step = Step.PRECOMBAT_MAIN
    apply_action(state, 0, CastSpell(bog.id, cast_for_free=True))
    resolve_top_of_stack(state)
    assert bog in state.players[0].graveyard and bog.plotted_turn == -1
    assert len(state.players[0].hand) == 2  # the duplicate + the found card


def test_plot_needs_mana():
    state = make_state()
    add(state, 0, BOG, Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    assert not any(
        isinstance(a, CastSpell) and a.use_plot for a in legal_actions(state, 0)
    )
