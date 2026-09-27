"""Cube W/G creatures: Ravenous + power-scaled tokens (Jacked Rabbit),
Mobilize + "opponents can't cast spells during your turn" (Voice of
Victory), Archon of Emeria's restrictions."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, PlayLand, apply_action
from mtg_bot.cards.parser.creature_wg_lines import parse_wg_creature_line
from mtg_bot.creature_statics_wg import (
    cast_forbidden,
    filter_cast_restrictions,
    forced_to_enter_tapped,
)
from mtg_bot.effects.generic.cube_creatures_wg import (
    CreateTokensEqualToSourcePower,
    EnteringWithXAtLeast,
    Mobilize,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._wg_helpers import (
    add_lands,
    attack,
    cast_and_resolve,
    cube,
    end_step,
    make_state,
    put,
)


def test_jacked_rabbit_ravenous_counters_and_draw():
    pr = cube()["Jacked Rabbit"]
    assert pr.enters_with_counters_from_x == "x"
    state = make_state()
    for _ in range(3):
        put(state, 0, "Plains", Zone.LIBRARY)
    rabbit = put(state, 0, pr, Zone.HAND)
    add_lands(state, 0, "Plains", 7)
    cast_and_resolve(state, 0, rabbit)  # agent pays the largest X = 5
    assert rabbit.plus_one_counters == 5
    assert len(state.players[0].hand) == 1


def test_jacked_rabbit_small_x_no_draw_and_attack_tokens():
    state = make_state()
    put(state, 0, "Plains", Zone.LIBRARY)
    rabbit = put(state, 0, "Jacked Rabbit", Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    state.players[0].agent.scripts["x"] = [2]
    cast_and_resolve(state, 0, rabbit)
    assert rabbit.plus_one_counters == 2 and state.players[0].hand == []
    rabbit.summoning_sick = False
    attack(state, 0, [rabbit.id])
    tokens = [o for o in state.battlefield if o.printing.name == "Rabbit"]
    assert len(tokens) == 3  # power 1 + 2 counters
    assert tokens[0].printing.color_indicator == frozenset({"W"})
    assert (tokens[0].printing.power, tokens[0].printing.toughness) == (1, 1)


def test_power_tokens_edge_cases():
    state = make_state()
    eff = next(
        t.effect for t in cube()["Jacked Rabbit"].triggered_abilities
        if isinstance(t.effect, CreateTokensEqualToSourcePower)
    )
    eff.resolve(state, 0)  # no source
    weak = put(state, 0, "Jacked Rabbit")
    weak.minus_one_counters = 1  # power 0
    state.resolving_source = weak
    eff.resolve(state, 0)
    state.resolving_source = None
    assert not any(o.printing.name == "Rabbit" for o in state.battlefield)
    assert "power" in eff.describe()
    assert EnteringWithXAtLeast(5).matches(state, {}, weak) is False


def test_voice_of_victory_mobilize_and_sacrifice():
    pr = cube()["Voice of Victory"]
    assert pr.opponents_cant_cast_spells_during_your_turn
    mob = next(t.effect for t in pr.triggered_abilities if isinstance(t.effect, Mobilize))
    assert mob.n == 2 and "mobilize 2" in mob.describe()
    state = make_state()
    voice = put(state, 0, pr)
    attack(state, 0, [voice.id])
    warriors = [o for o in state.battlefield if o.printing.name == "Warrior"]
    assert len(warriors) == 2
    assert all(w.tapped and w.attacking for w in warriors)
    assert all(w.printing.color_indicator == frozenset({"R"}) for w in warriors)
    end_step(state)
    assert not any(o.printing.name == "Warrior" for o in state.battlefield)


def test_voice_stops_opponent_casting_on_your_turn_only():
    state = make_state(step=Step.UPKEEP)
    put(state, 0, "Voice of Victory")
    bolt = put(state, 1, "Lightning Bolt", Zone.HAND)
    add_lands(state, 1, "Mountain", 1)
    state.active_player_idx = 0
    state.priority_player_idx = 1
    assert cast_forbidden(state, 1)
    assert not any(isinstance(a, CastSpell) for a in legal_actions(state, 1))
    state.active_player_idx = 1
    assert not cast_forbidden(state, 1)
    assert CastSpell(bolt.id) in legal_actions(state, 1)
    # The controller itself is never restricted.
    state.active_player_idx = 0
    assert not cast_forbidden(state, 0)


def test_archon_limits_each_player_to_one_spell():
    state = make_state()
    pr = cube()["Archon of Emeria"]
    assert pr.each_player_one_spell_per_turn
    assert "flying" in pr.keywords
    put(state, 0, pr)
    bolt = put(state, 0, "Lightning Bolt", Zone.HAND)
    put(state, 0, "Lightning Bolt", Zone.HAND)
    add_lands(state, 0, "Mountain", 2)
    assert CastSpell(bolt.id) in legal_actions(state, 0)
    state.players[1].agent.scripts["target"] = [("player", 1)]
    cast_and_resolve(state, 0, bolt)
    assert state.players[0].spells_cast_this_turn == 1
    assert not any(isinstance(a, CastSpell) for a in legal_actions(state, 0))
    plot = CastSpell(bolt.id, use_plot=True)
    assert filter_cast_restrictions(state, 0, [plot]) == [plot]


def test_archon_taps_opponents_nonbasic_lands():
    state = make_state()
    put(state, 0, "Archon of Emeria")
    state.active_player_idx = 1
    tomb = put(state, 1, "Ancient Tomb", Zone.HAND)
    basic = put(state, 1, "Mountain", Zone.HAND)
    apply_action(state, 1, PlayLand(tomb.id))
    assert tomb.tapped
    assert not forced_to_enter_tapped(state, basic, 1)
    # Its controller's own nonbasic lands are unaffected.
    mine = put(state, 0, "Ancient Tomb", Zone.HAND)
    assert not forced_to_enter_tapped(state, mine, 0)
    # A nonbasic land put onto the battlefield by an effect.
    from mtg_bot.actions import put_into_battlefield

    other = put(state, 1, "Ancient Tomb", Zone.HAND)
    state.players[1].hand.remove(other)
    put_into_battlefield(state, other, 1)
    assert other.tapped


def test_static_line_table_and_unknown_lines():
    assert parse_wg_creature_line("Mobilize X", {"name": "X"}) is None
    wg = parse_wg_creature_line("Mobilize 3", {"name": "X"})
    assert wg.triggers[0].effect == Mobilize(n=3)
    assert parse_wg_creature_line(
        "Each player can't cast more than one spell each turn.", {"name": "X"},
    ).fields == {"each_player_one_spell_per_turn": True}
